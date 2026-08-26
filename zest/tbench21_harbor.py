"""Harbor hub client for Terminal-Bench 2.1 trajectories.

2.1 moved off tbench.ai's embedded pages to the Harbor hub + GitHub:
- Entries live in GitHub `harbor-framework/terminal-bench-2-1` under
  `leaderboard/submissions/*.json`. Each submission = one agent/model entry and
  carries `source_jobs` (a job id), `trials` (~445 trial uuids), `metadata`
  (agent/model), and `disqualified_trials`.
- A trial's full ATIF trajectory is served as JSON from:
      https://hub.harborframework.com/api/trials/<trialId>/trajectory?jobId=<jobId>
  (verified ATIF-v1.7; same family as 2.0's v1.6, handled by parse.atif_trajectory).
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

from tqdm import tqdm

from . import net

HUB = "https://hub.harborframework.com"
GH_REPO = "harbor-framework/terminal-bench-2-1"
GH_API = f"https://api.github.com/repos/{GH_REPO}"
GH_RAW = f"https://raw.githubusercontent.com/{GH_REPO}/main"
SUBMISSIONS_DIR = "leaderboard/submissions"

HEADERS = {"User-Agent": "Mozilla/5.0 (zest-thesis harbor client)"}
DELAY_S = 0.1  # polite pause between hub requests
TIMEOUT = (10, 90)  # (connect, read) -- fail fast on a dead connection, but
                    # still allow slow legitimate transfers (some trajectory
                    # files run 100+ MB) up to 90s to complete


def _request(url: str, headers: dict | None = None):
    """TLS-tolerant GET. Returns the Response, or None on a connection-level
    failure (DNS/timeout/reset) -- callers decide how to read the status."""
    hdrs = {**HEADERS, **(headers or {})}
    return net.get(url, headers=hdrs, timeout=TIMEOUT)


def _get(url: str, as_json: bool = False, headers: dict | None = None, quiet: bool = False):
    """GET returning text (or parsed JSON), or None on any HTTP/network error
    so a single bad trial never aborts a bulk run. `quiet` suppresses the
    failure print for speculative attempts."""
    r = _request(url, headers)
    if r is None or not r.ok:
        if not quiet:
            code = r.status_code if r is not None else "?"
            tqdm.write(f"  ! fetch failed ({code}) {url.split('/')[-1][:40]}")
        return None
    try:
        return r.json() if as_json else r.text
    except ValueError:
        return None


def _get_status(url: str, headers: dict | None = None):
    """(status_code, json_or_None). status_code is None only on a total
    connection failure (no response at all) -- lets a caller tell a
    definitive 404 ("not present") apart from a transient failure worth
    retrying."""
    r = _request(url, headers)
    if r is None:
        return None, None
    if not r.ok:
        return r.status_code, None
    try:
        return r.status_code, r.json()
    except ValueError:
        return r.status_code, None


# ------------------------------------------------------------- GitHub entries

@dataclass
class Entry:
    """One leaderboard submission (agent/model) with its trials."""
    agent: str
    model: str
    job_id: str | None
    trial_ids: list[str] = field(default_factory=list)
    disqualified: set[str] = field(default_factory=set)

    @property
    def slug(self) -> str:
        safe = lambda s: "".join(c if c.isalnum() or c in "-._" else "-" for c in (s or "unknown"))
        return f"{safe(self.agent)}__{safe(self.model)}"


def list_submission_files() -> list[str]:
    """Return submission json paths from the GitHub repo tree."""
    tree = _get(f"{GH_API}/git/trees/main?recursive=1", as_json=True)
    if not tree:
        return []
    return sorted(
        p["path"] for p in tree.get("tree", [])
        if p["path"].startswith(SUBMISSIONS_DIR + "/") and p["path"].endswith(".json")
    )


def _extract_meta_name(meta: dict, *keys: str) -> str | None:
    for k in keys:
        v = meta.get(k)
        if isinstance(v, dict):
            v = v.get("name") or v.get("label") or v.get("value")
        if v:
            return str(v)
    return None


def load_entry(submission_path: str) -> Entry | None:
    doc = _get(f"{GH_RAW}/{submission_path}", as_json=True)
    if not doc:
        return None
    meta = doc.get("metadata", {}) or {}
    src_filter = doc.get("source_filter", {}) or {}
    agent = _extract_meta_name(meta, "agent_display", "agent") or src_filter.get("agent") or "unknown"
    model = (_extract_meta_name(meta, "model_display", "model")
             or src_filter.get("model_name") or "unknown")
    jobs = doc.get("source_jobs") or []
    job_id = jobs[0] if jobs else None

    trials = doc.get("trials") or []
    trial_ids = [t if isinstance(t, str) else t.get("id") or t.get("trial_id") for t in trials]
    trial_ids = [t for t in trial_ids if t]

    disq = set()
    for d in doc.get("disqualified_trials") or []:
        tid = d if isinstance(d, str) else d.get("trial_id") or d.get("id")
        if tid:
            disq.add(tid)

    return Entry(
        agent=agent,
        model=model,
        job_id=job_id,
        trial_ids=trial_ids,
        disqualified=disq,
    )


# ------------------------------------------------------------- trajectory API

DATASET = f"{HUB}/datasets/terminal-bench/terminal-bench-2-1/6/leaderboards/main"
_UUID = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
# a per-trial object in a hub row's RSC: "id":"<uuid>",...,"reward":<number>
_REWARD_RE = re.compile(r'"id":"(' + _UUID + r')"(?:(?!"id":).)*?"reward":(-?\d+(?:\.\d+)?)')


def leaderboard_row_ids() -> list[str]:
    """Row ids for each entry, from the hub leaderboard rows list (RSC payload)."""
    txt = _get(f"{DATASET}/rows", headers={"RSC": "1"})
    if not txt:
        return []
    u = txt.replace(chr(92) + '"', '"').replace(chr(92) + "/", "/")
    seen, out = set(), []
    for rid in re.findall(r"rows/(" + _UUID + ")", u):
        if rid not in seen:
            seen.add(rid)
            out.append(rid)
    return out


def rewards_by_trial() -> dict[str, float]:
    """Build a global {trial_id: reward} map by scanning every hub row once.
    Trial uuids are globally unique, so this applies to any downloaded trial."""
    rewards: dict[str, float] = {}
    row_ids = leaderboard_row_ids()
    for i, rid in enumerate(row_ids, 1):
        txt = _get(f"{DATASET}/rows/{rid}", headers={"RSC": "1"})
        if not txt:
            continue
        u = txt.replace(chr(92) + '"', '"')
        for tid, rw in _REWARD_RE.findall(u):
            rewards[tid] = float(rw)
        print(f"  rewards: row {i}/{len(row_ids)} -> {len(rewards)} trials mapped")
        time.sleep(DELAY_S)
    return rewards


def trajectory_url(trial_id: str, job_id: str) -> str:
    return f"{HUB}/api/trials/{trial_id}/trajectory?jobId={job_id}"


def trajectory_url_alt(trial_id: str, job_id: str) -> str:
    """Alternate hub path. Some trials 404 on the primary endpoint but
    resolve here (or vice versa) -- tried as a fallback, not primary,
    since the primary is the one proven across bulk runs."""
    return f"{HUB}/api/trials/{trial_id}/files/agent/trajectory.json?jobId={job_id}"


def config_url(trial_id: str, job_id: str) -> str:
    """Sibling of trajectory_url_alt's files/ path. Its `task.name` field
    (e.g. "terminal-bench/polyglot-rust-c") is the real, stable task
    identifier -- confirmed present with the same shape across 5 different
    entries/agents. The trajectory ATIF document itself and the GitHub
    submission file's `trials` list both carry no task info at all, so this
    is the only known source, and costs one extra request per trial."""
    return f"{HUB}/api/trials/{trial_id}/files/config.json?jobId={job_id}"


def fetch_task_name(trial_id: str, job_id: str) -> str | None:
    """The task name for one trial, or None if unavailable (transient
    failure or unexpected shape -- never cache a None as if it were
    confirmed-absent, unlike download_trajectory's 404 case, since we have
    no evidence this endpoint ever legitimately 404s for a real trial)."""
    doc = _get(config_url(trial_id, job_id), as_json=True, quiet=True)
    if not isinstance(doc, dict):
        return None
    task = doc.get("task")
    if not isinstance(task, dict):
        return None
    name = task.get("name")
    return str(name) if name else None


def _valid_atif(doc) -> bool:
    return bool(doc) and isinstance(doc, dict) and "schema_version" in doc


def download_trajectory(
    trial_id: str, job_id: str, dest: Path, overwrite: bool = False
) -> tuple[Path | None, bool]:
    """Download one trial's ATIF trajectory JSON to `dest`. Returns
    (dest_or_None, confirmed_empty). Any failure on the primary endpoint --
    404, connection error, 5xx, or an unexpected body -- gets exactly one
    retry via the alternate endpoint (some trials 404 on one but resolve on
    the other, in either direction). confirmed_empty is True only once BOTH
    endpoints have been tried and the final status is a clean 404 (safe to
    cache permanently); any other lingering failure is a transient one, not
    a confirmed absence, so it should be retried on a future run rather than
    cached."""
    if dest.exists() and not overwrite:
        return dest, False
    status, doc = _get_status(trajectory_url(trial_id, job_id))
    if not _valid_atif(doc):
        status, doc = _get_status(trajectory_url_alt(trial_id, job_id))
    if not _valid_atif(doc):
        return None, status == 404
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    if DELAY_S:
        time.sleep(DELAY_S)
    return dest, False
