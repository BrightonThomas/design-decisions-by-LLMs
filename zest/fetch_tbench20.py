"""Download Terminal-Bench reasoning trajectories from the tbench.ai leaderboard.

Each run's "Download Results" archive contains its ATIF-v1.6 trajectory, so
this fetches that archive via the site's download API and keeps just the
trajectory JSON (see zest.tbench20_web). Files are saved to
data/raw/tbench2.0/<uuid>-traj.json and parsed by `zest.parse --source tbench`.

Usage:
    # auto: walk the leaderboard and grab ~10 trajectories (across submissions)
    python -m zest.fetch_tbench20 --limit 10

    # explicit: download specific run OR submission pages (submission -> its runs)
    python -m zest.fetch_tbench20 --url https://www.tbench.ai/leaderboard/terminal-bench/2.0/.../<uuid>
    python -m zest.fetch_tbench20 --urls-file my_urls.txt

    # THE FULL CORPUS: every run of every task for every agent/model
    # (long-running, resumable -- already-downloaded files are skipped)
    python -m zest.fetch_tbench20 --all

    # just show what's already downloaded locally
    python -m zest.fetch_tbench20 --list-local

Notes:
- The leaderboard is public; no auth needed.
- One submission usually has only a handful of runs, so --limit 10 pulls from
  several submissions — which gives useful variety across agents/models.
"""

from __future__ import annotations

import argparse
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from tqdm import tqdm

from .paths import RAW_TBENCH20, ensure_dirs
from .tbench20_web import (
    MAX_WORKERS,
    download_from_leaderboard,
    download_run,
    expand_urls,
    no_archive_count,
    rewards_count,
    task_map_count,
)


def _startup_summary() -> None:
    ensure_dirs()
    n_downloaded = sum(1 for _ in RAW_TBENCH20.glob("*-traj.json"))
    print(f"Already downloaded: {n_downloaded}  |  "
          f"confirmed no-trajectory (skipped automatically): {no_archive_count()}  |  "
          f"known task ids: {task_map_count()}  |  "
          f"known outcomes: {rewards_count()}")


def list_local() -> None:
    ensure_dirs()
    files = sorted(
        f for f in RAW_TBENCH20.rglob("*")
        if f.is_file() and f.suffix in (".json", ".jsonl") and f.stem.endswith("-traj")
    )
    if not files:
        print(f"No trajectory files in {RAW_TBENCH20} yet. Run with --limit N to download.")
        return
    print(f"{len(files)} file(s) in {RAW_TBENCH20}:")
    for f in files:
        tag = "[not JSON]"
        try:
            obj = json.loads(f.read_text(encoding="utf-8", errors="replace"))
            sv = obj.get("schema_version") if isinstance(obj, dict) else None
            agent = (obj.get("agent") or {}).get("name") if isinstance(obj, dict) else None
            tag = f"[{sv}, agent={agent}]" if sv else "[non-ATIF JSON]"
        except (json.JSONDecodeError, AttributeError):
            pass
        print(f"  {f.name}  {tag}")


def _download_all(run_urls: list[str], limit: int | None, overwrite: bool) -> int:
    """Download until `limit` trajectories succeed, or all of them if `limit`
    is None (candidates may fail server-side). With no limit, every URL is
    wanted anyway, so there's no early-stopping to preserve -- run them
    concurrently instead of one at a time."""
    if limit is None:
        saved = 0
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
            futures = ex.map(lambda u: download_run(u, overwrite=overwrite), run_urls)
            for ok in tqdm(futures, total=len(run_urls), desc="runs", unit="run"):
                if ok:
                    saved += 1
        return saved
    saved = 0
    for url in tqdm(run_urls, desc="runs", unit="run"):
        if saved >= limit:
            break
        if download_run(url, overwrite=overwrite):
            saved += 1
    return saved


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--limit", type=int, default=10, help="max trajectories to download (default: 10)")
    ap.add_argument("--per-agent", type=int, default=1,
                    help="max runs to take from each agent/model when auto-enumerating "
                         "(default: 1, for cross-scaffold variety; raise to sample one agent deeper)")
    ap.add_argument("--all", action="store_true",
                    help="download every run of every task for every agent/model (full corpus; "
                         "long-running). Overrides --limit/--per-agent.")
    ap.add_argument("--url", action="append", default=[], metavar="URL",
                    help="a run or submission page URL (repeatable); overrides auto-enumeration")
    ap.add_argument("--urls-file", type=Path, help="text file with one run/submission URL per line")
    ap.add_argument("--overwrite", action="store_true", help="re-download files that already exist")
    ap.add_argument("--list-local", action="store_true", help="list already-downloaded files and exit")
    args = ap.parse_args()

    if args.list_local:
        list_local()
        return

    _startup_summary()

    explicit = list(args.url)
    if args.urls_file:
        explicit += [ln for ln in args.urls_file.read_text(encoding="utf-8").splitlines() if ln.strip()]

    limit = None if args.all else args.limit
    per_agent = None if args.all else args.per_agent
    max_tasks_per_agent = None if args.all else 4

    if explicit:
        print(f"Expanding {len(explicit)} URL(s)...")
        run_urls = expand_urls(explicit)
        if not run_urls:
            print("No run URLs to download.")
            return
        print(f"Downloading up to {limit if limit is not None else 'all'} of {len(run_urls)} run(s) into {RAW_TBENCH20}:")
        saved = _download_all(run_urls, limit, args.overwrite)
    else:
        target = "all trajectories" if args.all else f"up to {limit} trajectories"
        print(f"Walking the tbench.ai leaderboard for {target} into {RAW_TBENCH20}:")
        saved = download_from_leaderboard(
            limit, per_agent=per_agent, overwrite=args.overwrite,
            max_tasks_per_agent=max_tasks_per_agent,
        )

    print(f"\nDone: {saved} trajectory file(s) ready.")
    if not args.all and saved < args.limit:
        print(f"(Wanted {args.limit}; many leaderboard runs don't publish a trajectory. "
              f"Re-run to continue, raise --per-agent, or pass --url for specific runs.)")
    print("Next: python -m zest.parse --source tbench")


if __name__ == "__main__":
    main()
