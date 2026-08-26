"""Mine Terminal-Bench 2.1 trajectories from the Harbor hub.

Entries come from GitHub `harbor-framework/terminal-bench-2-1`
(`leaderboard/submissions/*.json`); each trial's ATIF-v1.7 trajectory is
downloaded from the hub trajectory API. Files land in
`data/raw/tbench2.1/<agent>__<model>/<trialId>-traj.json`, plus a
`_rewards.json` map (trial_id -> pass/fail reward) for the `resolved` field.

Resumable: already-downloaded files are skipped, so re-running continues.

Usage:
    # list the entries (no download)
    python -m zest.fetch_tbench21 --list

    # demo: a few trajectories from each of the first 2 entries
    python -m zest.fetch_tbench21 --limit-per-entry 5 --max-entries 2

    # one entry by name substring, all its trials
    python -m zest.fetch_tbench21 --entry gemini-cli

    # THE FULL CORPUS (~6000+ trajectories; long-running, resumable)
    python -m zest.fetch_tbench21 --all

    # also fetch the pass/fail rewards map (adds ~20 hub requests)
    python -m zest.fetch_tbench21 --all --rewards
"""

from __future__ import annotations

import argparse
import json
from concurrent.futures import ThreadPoolExecutor, as_completed

from tqdm import tqdm

from . import tbench21_harbor as harbor
from .paths import RAW_TBENCH21, ensure_dirs, replace_with_retry

_NO_TRAJECTORY_FILE = "_no_trajectory.json"
_TASK_NAMES_FILE = "_task_names.json"
MAX_WORKERS = 16  # concurrent hub requests -- I/O-bound waits dominate, so
                  # this is what actually cuts wall-clock time on --all


def _matches(entry: harbor.Entry, substr: str | None) -> bool:
    return substr is None or substr.lower() in entry.slug.lower()


def _load_no_trajectory() -> set[str]:
    """Trial ids confirmed (on a previous run) to have no published
    trajectory. Trial ids are globally unique, so one flat file covers every
    entry -- same reasoning as the existing `_rewards.json` sidecar."""
    f = RAW_TBENCH21 / _NO_TRAJECTORY_FILE
    if not f.exists():
        return set()
    try:
        return set(json.loads(f.read_text(encoding="utf-8")))
    except json.JSONDecodeError:
        return set()


def _save_no_trajectory(ids: set[str]) -> None:
    """Saved immediately as each new miss is confirmed (see mine()), not
    batched, so an interrupted run keeps its progress. Only ever called from
    the main thread (as_completed() results are consumed there), so no lock
    is needed despite downloads running on worker threads.

    `ids` is the caller's in-memory set, already updated by the time this is
    called -- if the disk persist itself fails (e.g. Windows antivirus/
    indexer briefly holding the file), that's not fatal to the run, just
    logged; the next successful write will include this id too."""
    dest = RAW_TBENCH21 / _NO_TRAJECTORY_FILE
    tmp = dest.with_suffix(dest.suffix + ".tmp")
    tmp.write_text(json.dumps(sorted(ids)), encoding="utf-8")
    try:
        replace_with_retry(tmp, dest)
    except PermissionError:
        tqdm.write("  ! couldn't persist no-trajectory cache to disk this time "
                   "(still tracked in memory for this run)")


def _load_task_names() -> dict[str, str]:
    """Trial id -> task name (e.g. "terminal-bench/polyglot-rust-c"), the
    real cross-agent-stable task identifier -- see
    tbench21_harbor.fetch_task_name's docstring for why this is the only
    known source of it. Trial ids are globally unique, same reasoning as
    _load_no_trajectory."""
    f = RAW_TBENCH21 / _TASK_NAMES_FILE
    if not f.exists():
        return {}
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _save_task_names(names: dict[str, str]) -> None:
    """Saved immediately as each new name is found, not batched -- same
    reasoning as _save_no_trajectory."""
    dest = RAW_TBENCH21 / _TASK_NAMES_FILE
    tmp = dest.with_suffix(dest.suffix + ".tmp")
    tmp.write_text(json.dumps(names), encoding="utf-8")
    try:
        replace_with_retry(tmp, dest)
    except PermissionError:
        tqdm.write("  ! couldn't persist task-names cache to disk this time "
                   "(still tracked in memory for this run)")


def list_entries() -> None:
    """List entries available on the Harbor/GitHub leaderboard (remote —
    not what's already downloaded locally; there's no local-file lister for
    this pipeline since output is nested per-entry, unlike fetch_tbench20's
    flat directory)."""
    files = harbor.list_submission_files()
    print(f"{len(files)} entries:")
    for f in files:
        e = harbor.load_entry(f)
        if e:
            print(f"  {e.slug:45}  trials={len(e.trial_ids):4}  disq={len(e.disqualified)}  job={(e.job_id or '')[:12]}")


def save_rewards() -> int:
    ensure_dirs()
    RAW_TBENCH21.mkdir(parents=True, exist_ok=True)
    print("Building trial->reward map from hub rows...")
    rewards = harbor.rewards_by_trial()
    (RAW_TBENCH21 / "_rewards.json").write_text(json.dumps(rewards), encoding="utf-8")
    print(f"Saved {len(rewards)} rewards -> {RAW_TBENCH21/'_rewards.json'}")
    return len(rewards)


def mine(limit_per_entry: int | None, max_entries: int | None,
         entry_filter: str | None, overwrite: bool) -> int:
    ensure_dirs()
    files = harbor.list_submission_files()
    if not files:
        print("No submission files found on GitHub.")
        return 0

    no_trajectory = _load_no_trajectory()
    task_names = _load_task_names()
    n_downloaded = sum(1 for _ in RAW_TBENCH21.rglob("*-traj.json"))
    print(f"Already downloaded: {n_downloaded}  |  "
          f"confirmed no-trajectory (skipped automatically): {len(no_trajectory)}  |  "
          f"known task names: {len(task_names)}")

    total = 0
    entries_done = 0
    for f in tqdm(files, desc="entries", unit="entry"):
        if max_entries is not None and entries_done >= max_entries:
            break
        entry = harbor.load_entry(f)
        if not entry or not _matches(entry, entry_filter):
            continue
        if not entry.job_id:
            tqdm.write(f"  skip {entry.slug}: no source job id")
            continue

        entries_done += 1
        dest_dir = RAW_TBENCH21 / entry.slug
        trials = [t for t in entry.trial_ids if t not in entry.disqualified]
        if limit_per_entry is not None:
            trials = trials[:limit_per_entry]

        # Resolve what's already known (on disk, or a confirmed prior miss)
        # without any network call; only genuinely unresolved trials are
        # queried, and those run concurrently instead of one at a time.
        to_query = []
        skipped = 0
        for tid in trials:
            dest = dest_dir / f"{tid}-traj.json"
            if not overwrite and (dest.exists() or tid in no_trajectory):
                skipped += 1
            else:
                to_query.append(tid)
        tqdm.write(f"[{entry.slug}] {len(trials)} trials, {len(to_query)} to fetch "
                   f"(job {entry.job_id[:12]})")

        saved = failed = 0
        pbar = tqdm(total=len(to_query), desc=entry.slug, unit="trial", leave=False)
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
            futures = {
                ex.submit(harbor.download_trajectory, tid, entry.job_id,
                          dest_dir / f"{tid}-traj.json", overwrite): tid
                for tid in to_query
            }
            for fut in as_completed(futures):
                tid = futures[fut]
                result, confirmed_empty = fut.result()
                if result:
                    saved += 1
                    tqdm.write(f"  + {result.name}")
                else:
                    failed += 1
                    tqdm.write(f"  ! no trajectory: trial {tid} (entry {entry.slug})")
                    if confirmed_empty and tid not in no_trajectory:
                        # saved immediately, not batched -- see _save_no_trajectory
                        no_trajectory.add(tid)
                        _save_no_trajectory(no_trajectory)
                pbar.update(1)
                pbar.set_postfix(saved=saved, skipped=skipped, failed=failed)
        pbar.close()
        total += saved
        tqdm.write(f"    saved {saved}, skipped(existing) {skipped}, no-trajectory {failed}")

        # Task-name backfill: independent of trajectory-download status, so
        # this also fills in names for trials already downloaded on a prior
        # run -- runs over the entry's full trial list, not just to_query.
        to_name = [tid for tid in trials if tid not in task_names]
        if to_name:
            named = 0
            npbar = tqdm(total=len(to_name), desc=f"{entry.slug} (names)", unit="trial", leave=False)
            with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
                name_futures = {
                    ex.submit(harbor.fetch_task_name, tid, entry.job_id): tid
                    for tid in to_name
                }
                for fut in as_completed(name_futures):
                    tid = name_futures[fut]
                    name = fut.result()
                    if name:
                        task_names[tid] = name
                        _save_task_names(task_names)
                        named += 1
                    npbar.update(1)
            npbar.close()
            tqdm.write(f"    task names: {named}/{len(to_name)} resolved")
    print(f"\nTotal new trajectories: {total} -> {RAW_TBENCH21}")
    print(f"Confirmed non-existent trajectories (cached): {len(no_trajectory)}")
    print(f"Known task names (cached): {len(task_names)}")
    print("Next: python -m zest.parse --source tbench21")
    return total


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--list", action="store_true", help="list entries and exit")
    ap.add_argument("--all", action="store_true", help="download all trials of all entries (full corpus)")
    ap.add_argument("--limit-per-entry", type=int, default=5,
                    help="max trials per entry when not --all (default: 5)")
    ap.add_argument("--max-entries", type=int, default=None, help="cap number of entries processed")
    ap.add_argument("--entry", default=None, help="only entries whose slug contains this substring")
    ap.add_argument("--rewards", action="store_true", help="also build the trial->reward (pass/fail) map")
    ap.add_argument("--overwrite", action="store_true", help="re-download existing files")
    args = ap.parse_args()

    if args.list:
        list_entries()
        return

    limit_per_entry = None if args.all else args.limit_per_entry
    max_entries = None if args.all else args.max_entries
    mine(limit_per_entry, max_entries, args.entry, args.overwrite)
    if args.rewards:
        save_rewards()


if __name__ == "__main__":
    main()
