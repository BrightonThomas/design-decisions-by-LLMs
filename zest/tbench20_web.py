"""Download Terminal-Bench trajectories straight from the tbench.ai leaderboard.

The "Download Results" button on a run page is a Next.js Server Action
(`getTrialFileDownloadUrl`, invoked by POSTing to the run page's own URL with
a `Next-Action` header) that returns a short-lived Supabase Storage signed URL
for a `.tar.gz` archive. That archive contains `<task>/agent/trajectory.json`
(ATIF-v1.6) plus other per-trial files we don't need — we fetch the archive
in memory and keep only the trajectory JSON.

The `Next-Action` id below is a content hash tied to tbench.ai's current
deployment; if the site redeploys, it will go stale and every download will
start failing with "no results archive available". To find the new id,
search the page's JS chunks (referenced from `self.__next_f.push([...])` in
the page HTML) for `getTrialFileDownloadUrl`.

URL shapes:
  submission page:  /leaderboard/terminal-bench/2.0/<agent>/<ver>/<model>/<subhash>
  run page:         /leaderboard/terminal-bench/2.0/<agent>/<ver>/<model>/<subhash>/<run-uuid>
A submission page lists its run UUIDs; a run URL is the submission URL + '/' + uuid.
The run UUID doubles as the trialId the server action expects.
"""

from __future__ import annotations

import io
import json
import re
import tarfile
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import quote

import requests
from tqdm import tqdm

from . import net
from .paths import RAW_TBENCH20, ensure_dirs, replace_with_retry

BASE = "https://www.tbench.ai"
LEADERBOARD = f"{BASE}/leaderboard/terminal-bench/2.0"
HEADERS = {"User-Agent": "Mozilla/5.0 (zest-thesis trajectory fetcher)"}
MAX_WORKERS = 16  # concurrent requests during --all; I/O-bound waits, not CPU,
                  # so this is what actually cuts wall-clock time -- no
                  # self-imposed rate limit beyond this pool size

ACTION_ID = "608f984391f21c00d5d8b98175d8218a983633e5e5"  # getTrialFileDownloadUrl
ACTION_HEADERS = {
    **HEADERS,
    "Next-Action": ACTION_ID,
    "Content-Type": "text/plain;charset=UTF-8",
    "Accept": "text/x-component",
}
_ACTION_URL_RE = re.compile(r'^\d+:"(https://[^\n]*?)"\s*$', re.MULTILINE)

UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
SUBHASH_RE = re.compile(r"[0-9a-f]{64}")  # submission hash on an agent/model page

_NO_ARCHIVE_FILE = "_no_archive.json"
_no_archive_cache: set[str] | None = None
_no_archive_lock = threading.Lock()  # download_run() runs on worker threads
                                      # under --all; guards the read-modify-
                                      # write on the shared cache/file

_TASK_MAP_FILE = "_task_map.json"
_task_map_cache: dict[str, str] | None = None
_task_map_lock = threading.Lock()

_REWARDS_FILE = "_rewards.json"
_rewards_cache: dict[str, float] | None = None
_rewards_lock = threading.Lock()

# A task page's Next.js flight data embeds one object per trial with both
# its run uuid (trialId) and pass/fail outcome (reward) next to each other,
# e.g. "trialId":"<uuid>","trialName":"...","taskName":"...","reward":1,...
# -- same page runs_for_submission() already fetches for the uuid list, so
# rewards are scraped as a side effect there instead of costing a second
# request per task page.
_TRIAL_REWARD_RE = re.compile(
    r'"trialId":"(' + UUID_RE.pattern + r')"(?:(?!"trialId":).)*?"reward":(-?\d+(?:\.\d+)?)'
)

# The leaderboard page embeds entries in Next.js flight data (backslash-escaped
# JSON). Each entry carries the fields needed to build its agent/model URL:
#   /leaderboard/terminal-bench/2.0/<agentName>/<agentVersion>/<model>%40<provider>
_ENTRY_RE = re.compile(
    r'"agentName":"(?P<agent>[^"]*)",'
    r'"agentVersion":"(?P<ver>[^"]*)",'
    r'"modelNames":\["(?P<model>[^"]*)"[^\]]*\],'
    r'"modelProviders":\["(?P<provider>[^"]*)"'
)


def _no_archive() -> set[str]:
    """UUIDs confirmed (on a previous run) to have no results archive to
    offer. Loaded once and cached in memory; only ever grown, never re-read,
    for the life of a process."""
    global _no_archive_cache
    if _no_archive_cache is None:
        f = RAW_TBENCH20 / _NO_ARCHIVE_FILE
        try:
            _no_archive_cache = set(json.loads(f.read_text(encoding="utf-8"))) if f.exists() else set()
        except json.JSONDecodeError:
            _no_archive_cache = set()
    return _no_archive_cache


def no_archive_count() -> int:
    """How many UUIDs are confirmed to have no archive, so a caller can print
    a startup summary before doing any network work."""
    return len(_no_archive())


def _mark_no_archive(uuid: str) -> None:
    """Record `uuid` as confirmed-empty so future runs skip it without a
    network call. Only call this for a definitive result, never a
    network/HTTP-level failure -- those should be retried, not blacklisted.
    Saved immediately (not batched) so an interrupted run keeps its progress;
    lock + atomic replace because this runs on worker threads under --all.
    The in-memory set is updated first and is what every future skip-check
    in this process actually reads, so if the disk persist itself fails
    (e.g. Windows antivirus/indexer briefly holding the file) that's not
    fatal to the run -- just logged; the next successful write will include
    this uuid too."""
    ensure_dirs()
    with _no_archive_lock:
        _no_archive().add(uuid)
        dest = RAW_TBENCH20 / _NO_ARCHIVE_FILE
        tmp = dest.with_suffix(dest.suffix + ".tmp")
        tmp.write_text(json.dumps(sorted(_no_archive())), encoding="utf-8")
        try:
            replace_with_retry(tmp, dest)
        except PermissionError:
            tqdm.write(f"  ! couldn't persist no-archive cache to disk this time "
                       f"(uuid {uuid[:8]}… still tracked in memory for this run)")


def _task_map() -> dict[str, str]:
    """uuid -> task checksum. The checksum (not ATIF's own session_id field,
    which is an unrelated per-run value) is the real, stable task identifier
    shared across every agent/model that ran the same task -- see
    submissions_for_agent_model's docstring. Loaded once, only ever grown,
    for the life of a process."""
    global _task_map_cache
    if _task_map_cache is None:
        f = RAW_TBENCH20 / _TASK_MAP_FILE
        try:
            _task_map_cache = json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}
        except json.JSONDecodeError:
            _task_map_cache = {}
    return _task_map_cache


def task_map_count() -> int:
    """How many uuids have a known task checksum, for a startup summary."""
    return len(_task_map())


def _task_checksum(run_url: str) -> str | None:
    """The task checksum is the run URL's second-to-last path segment:
    .../<checksum>/<run-uuid>."""
    parts = run_url.rstrip("/").split("/")
    if len(parts) >= 2 and SUBHASH_RE.fullmatch(parts[-2]):
        return parts[-2]
    return None


def _record_task_checksum(uuid: str, checksum: str) -> None:
    """Record uuid -> task checksum. download_run() calls this for every
    run_url it sees regardless of outcome (already-downloaded, no-archive,
    or fresh success), so simply re-running --all backfills this map for
    every already-downloaded file too -- no separate backfill pass needed.
    Skips the write entirely once already recorded, so repeat runs are
    nearly free. Lock + atomic replace because this runs on worker threads."""
    with _task_map_lock:
        m = _task_map()
        if m.get(uuid) == checksum:
            return
        m[uuid] = checksum
        ensure_dirs()
        dest = RAW_TBENCH20 / _TASK_MAP_FILE
        tmp = dest.with_suffix(dest.suffix + ".tmp")
        tmp.write_text(json.dumps(m), encoding="utf-8")
        try:
            replace_with_retry(tmp, dest)
        except PermissionError:
            tqdm.write(f"  ! couldn't persist task-checksum map to disk this time "
                       f"(uuid {uuid[:8]}… still tracked in memory for this run)")


def _rewards() -> dict[str, float]:
    """uuid -> reward (0/1), scraped as a side effect of runs_for_submission().
    Loaded once, only ever grown, for the life of a process."""
    global _rewards_cache
    if _rewards_cache is None:
        f = RAW_TBENCH20 / _REWARDS_FILE
        try:
            _rewards_cache = json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}
        except json.JSONDecodeError:
            _rewards_cache = {}
    return _rewards_cache


def rewards_count() -> int:
    """How many uuids have a known pass/fail reward, for a startup summary."""
    return len(_rewards())


def _record_rewards_from_html(html: str) -> None:
    """Extract {trialId: reward} pairs embedded in a task page's Next.js
    flight data and merge new/changed ones into the on-disk rewards cache.
    Safe to call from multiple threads (runs_for_submission runs on worker
    threads under --all); a no-op write when nothing changed."""
    unescaped = html.replace(chr(92) + '"', '"')
    pairs = _TRIAL_REWARD_RE.findall(unescaped)
    if not pairs:
        return
    with _rewards_lock:
        rewards = _rewards()
        changed = False
        for uuid, reward in pairs:
            val = float(reward)
            if rewards.get(uuid) != val:
                rewards[uuid] = val
                changed = True
        if not changed:
            return
        ensure_dirs()
        dest = RAW_TBENCH20 / _REWARDS_FILE
        tmp = dest.with_suffix(dest.suffix + ".tmp")
        tmp.write_text(json.dumps(rewards), encoding="utf-8")
        try:
            replace_with_retry(tmp, dest)
        except PermissionError:
            tqdm.write("  ! couldn't persist rewards cache to disk this time "
                       "(still tracked in memory for this run)")


def _get(url: str) -> str | None:
    """GET a page as text, or None on any HTTP/network error (so a single bad
    page never crashes an enumeration/download run — some agent+task combos
    500 or 404 server-side)."""
    r = net.get(url, headers=HEADERS, timeout=60)
    if r is None:
        tqdm.write(f"  ! fetch failed (?) for {url.rsplit('/', 1)[-1][:16]}… — skipping")
        return None
    try:
        r.raise_for_status()
    except requests.exceptions.RequestException:
        tqdm.write(f"  ! fetch failed ({r.status_code}) for {url.rsplit('/', 1)[-1][:16]}… — skipping")
        return None
    return r.text


def _request_download_url(run_url: str, trial_id: str, file_type: str = "tarGz") -> tuple[str | None, bool]:
    """Invoke the `getTrialFileDownloadUrl` server action for a run page.
    Returns (signed_url, confirmed_empty). `confirmed_empty` is True only
    when the server responded successfully but simply had no archive URL to
    offer -- a stable fact about this trial, safe to cache. It's False for
    any network/HTTP-level failure, which is transient and worth retrying.
    The URL is only valid for ~60s, so callers should fetch it immediately."""
    body = json.dumps([trial_id, file_type])
    r = net.post(run_url, headers=ACTION_HEADERS, data=body, timeout=60)
    if r is None:
        tqdm.write(f"  ! download-url request failed (?) for {trial_id[:8]}…")
        return None, False
    try:
        r.raise_for_status()
    except requests.exceptions.RequestException:
        tqdm.write(f"  ! download-url request failed ({r.status_code}) for {trial_id[:8]}…")
        return None, False

    m = _ACTION_URL_RE.search(r.text)
    if not m:
        return None, True
    try:
        return json.loads(f'"{m.group(1)}"'), False
    except json.JSONDecodeError:
        return m.group(1), False


def _get_bytes(url: str) -> bytes | None:
    """GET a URL and return its raw bytes, or None on any HTTP/network error."""
    r = net.get(url, headers=HEADERS, timeout=60)
    if r is None:
        tqdm.write("  ! archive fetch failed (?)")
        return None
    try:
        r.raise_for_status()
    except requests.exceptions.RequestException:
        tqdm.write(f"  ! archive fetch failed ({r.status_code})")
        return None
    return r.content


def _extract_trajectory_from_targz(data: bytes) -> dict | None:
    """Pull `agent/trajectory.json` out of a run's results .tar.gz archive."""
    try:
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tf:
            member = next(
                (m for m in tf.getmembers()
                 if m.name.endswith("/agent/trajectory.json") or m.name == "trajectory.json"),
                None,
            )
            if member is None:
                return None
            f = tf.extractfile(member)
            if f is None:
                return None
            return json.loads(f.read().decode("utf-8"))
    except (tarfile.TarError, json.JSONDecodeError):
        return None


def _run_uuid(run_url: str) -> str:
    m = UUID_RE.search(run_url)
    return m.group(0) if m else run_url.rstrip("/").rsplit("/", 1)[-1]


def download_run(run_url: str, overwrite: bool = False) -> Path | None:
    """Download a run's results archive and save its ATIF trajectory as
    <uuid>-traj.json."""
    ensure_dirs()
    uuid = _run_uuid(run_url)
    checksum = _task_checksum(run_url)
    if checksum:
        _record_task_checksum(uuid, checksum)
    dest = RAW_TBENCH20 / f"{uuid}-traj.json"
    if dest.exists() and not overwrite:
        tqdm.write(f"  = {dest.name} (already downloaded)")
        return dest
    if not overwrite and uuid in _no_archive():
        tqdm.write(f"  = {uuid}: skipping (confirmed no archive on a previous run)")
        return None

    url, confirmed_empty = _request_download_url(run_url, uuid, "tarGz")
    if not url:
        tqdm.write(f"  x {uuid}: no results archive available (or download API changed)")
        if confirmed_empty:
            _mark_no_archive(uuid)
        return None
    data = _get_bytes(url)
    if not data:
        tqdm.write(f"  x {uuid}: failed to fetch results archive")
        return None
    traj = _extract_trajectory_from_targz(data)
    if traj is None or "schema_version" not in traj:
        tqdm.write(f"  x {uuid}: no trajectory.json in results archive")
        _mark_no_archive(uuid)
        return None

    dest.write_text(json.dumps(traj, ensure_ascii=False, indent=2), encoding="utf-8")
    agent = (traj.get("agent") or {}).get("name")
    nsteps = len(traj.get("steps", []))
    tqdm.write(f"  + {dest.name}  [agent={agent}, steps={nsteps}]")
    return dest


def runs_for_submission(submission_url: str) -> list[str]:
    """List run-page (trial) URLs for a task page (task URL + '/' + uuid).
    Also records each trial's pass/fail reward from the same page (see
    _record_rewards_from_html) -- no extra request, since the page is
    already being fetched here for the uuid list."""
    html = _get(submission_url)
    if not html:
        return []
    _record_rewards_from_html(html)
    base = submission_url.rstrip("/")
    uuids = sorted(set(UUID_RE.findall(html)))
    return [f"{base}/{u}" for u in uuids]


def _is_submission_url(url: str) -> bool:
    # submission URL ends with a long hex hash; run URL ends with a UUID
    tail = url.rstrip("/").rsplit("/", 1)[-1]
    return bool(re.fullmatch(r"[0-9a-f]{32,}", tail))


def expand_urls(urls: list[str]) -> list[str]:
    """Turn a mix of run/submission URLs into a flat list of run URLs."""
    out: list[str] = []
    for u in urls:
        u = u.strip().rstrip("\\")
        if not u:
            continue
        if _is_submission_url(u):
            found = runs_for_submission(u)
            tqdm.write(f"  submission {u.rsplit('/', 1)[-1][:12]}… -> {len(found)} runs")
            out.extend(found)
        else:
            out.append(u)
    return out


def leaderboard_agent_model_urls() -> list[str]:
    """Parse leaderboard entries into agent/model page URLs.

    URL shape: /2.0/<agentName>/<agentVersion>/<model>%40<provider>
    (the '@' between model and provider is percent-encoded as %40).
    """
    raw = _get(LEADERBOARD)
    if not raw:
        return []
    html = raw.replace(chr(92) + '"', '"')  # unescape \" -> "
    urls: list[str] = []
    seen: set[str] = set()
    for m in _ENTRY_RE.finditer(html):
        agent, ver, model, provider = m.group("agent", "ver", "model", "provider")
        path = f"{quote(agent)}/{quote(ver)}/{quote(model)}%40{quote(provider)}"
        if path not in seen:
            seen.add(path)
            urls.append(f"{LEADERBOARD}/{path}")
    return urls


def submissions_for_agent_model(agent_model_url: str) -> list[str]:
    """List task-page URLs for an agent/model (agent/model URL + '/' + taskChecksum).
    The 64-hex values on the page are task checksums; each task page holds that
    agent's trial runs for the task."""
    html = _get(agent_model_url)
    if not html:
        return []
    base = agent_model_url.rstrip("/")
    # preserve page order (best/primary submission tends to appear first),
    # dedupe while keeping first occurrence
    seen, hashes = set(), []
    for h in SUBHASH_RE.findall(html):
        if h not in seen:
            seen.add(h)
            hashes.append(h)
    return [f"{base}/{h}" for h in hashes]


def _reached(n: int, cap: int | None) -> bool:
    return cap is not None and n >= cap


def _download_from_leaderboard_all(overwrite: bool) -> int:
    """Full-corpus path (limit/per_agent/max_tasks_per_agent all None): every
    run is wanted anyway, so there's no early-stopping to preserve and both
    enumeration and download can run on a thread pool instead of one request
    at a time. This is what actually makes --all fast: each individual
    request only takes ~1s, but a full corpus is tens of thousands of them,
    so doing them serially is what made it feel slow, not the requests
    themselves."""
    agent_models = leaderboard_agent_model_urls()
    if not agent_models:
        print(
            "  ! Could not parse leaderboard entries (site structure may have changed).\n"
            "    Pass explicit run/submission URLs with --url instead."
        )
        return 0
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        task_lists = list(tqdm(
            ex.map(submissions_for_agent_model, agent_models),
            total=len(agent_models), desc="agent/model entries", unit="entry",
        ))
    task_urls = [u for lst in task_lists for u in lst]

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        run_lists = list(tqdm(
            ex.map(runs_for_submission, task_urls),
            total=len(task_urls), desc="task pages", unit="page",
        ))
    run_urls = [u for lst in run_lists for u in lst]

    saved = missing = 0
    pbar = tqdm(total=len(run_urls), desc="runs", unit="run")
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futures = {ex.submit(download_run, u, overwrite): u for u in run_urls}
        for fut in as_completed(futures):
            result = fut.result()
            if result is not None:
                saved += 1
            else:
                missing += 1
            pbar.update(1)
            pbar.set_postfix(saved=saved, no_trajectory=missing)
    pbar.close()
    print(f"  confirmed non-existent (cached): {no_archive_count()}")
    return saved


def download_from_leaderboard(
    limit: int | None, per_agent: int | None = 1, overwrite: bool = False,
    max_tasks_per_agent: int | None = 4,
) -> int:
    """Stream leaderboard -> agent/model -> task -> trial, downloading trajectories
    until `limit` succeed (or without limit if `limit` is None). Interleaving
    download with enumeration lets us skip the many runs that don't publish an
    ATIF trajectory and still reach the target, while `per_agent` keeps the
    sample spread across scaffolds/models.

    Per agent/model: try tasks in page order (up to `max_tasks_per_agent`, or
    all of them if None), downloading trials until `per_agent` succeed, then
    move on. Returns the count of trajectories saved."""
    if limit is None and per_agent is None and max_tasks_per_agent is None:
        return _download_from_leaderboard_all(overwrite)

    agent_models = leaderboard_agent_model_urls()
    if not agent_models:
        print(
            "  ! Could not parse leaderboard entries (site structure may have changed).\n"
            "    Pass explicit run/submission URLs with --url instead."
        )
        return 0
    print(f"  found {len(agent_models)} agent/model entries; downloading "
          f"{'up to ' + str(limit) if limit is not None else 'all'} trajectories "
          f"({per_agent if per_agent is not None else 'all'} per agent for variety)...")

    saved = 0
    pbar = tqdm(total=limit, desc="trajectories", unit="traj")
    for am_url in agent_models:
        if _reached(saved, limit):
            break
        taken = 0
        task_urls = submissions_for_agent_model(am_url)
        if max_tasks_per_agent is not None:
            task_urls = task_urls[:max_tasks_per_agent]
        for task_url in task_urls:
            if _reached(taken, per_agent) or _reached(saved, limit):
                break
            for run_url in runs_for_submission(task_url):
                if download_run(run_url, overwrite=overwrite):
                    saved += 1
                    taken += 1
                    pbar.update(1)
                if _reached(taken, per_agent) or _reached(saved, limit):
                    break
    pbar.close()
    return saved
