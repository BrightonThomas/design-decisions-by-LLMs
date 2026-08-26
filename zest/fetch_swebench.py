"""Fetch a small sample of reasoning trajectories from SWE-bench leaderboard
submissions (github.com/swe-bench/experiments).

Submissions live under evaluation/<split>/<date_modelname>/. Older/smaller
submissions keep a trajs/ folder in the git repo; most submissions instead
point to a trajs/ prefix in the public `swe-bench-submissions` S3 bucket
(the exact path is in each submission's metadata.yaml, under `assets.trajs`)
— confirmed publicly readable (no auth) via its list-objects-v2 XML API, so
this fetcher tries the repo first and falls back to S3 automatically.

Demo scale: downloads trajectories from ONE submission, default limit 10.

Usage:
    python -m zest.fetch_swebench --list
    python -m zest.fetch_swebench --list --split lite
    python -m zest.fetch_swebench --submission 20240402_sweagent_gpt4 --split lite
    python -m zest.fetch_swebench --submission <name> --split verified --limit 10

Set a GITHUB_TOKEN environment variable to avoid the 60 requests/hour
unauthenticated GitHub API rate limit.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import xml.etree.ElementTree as ET

import requests

from .paths import RAW_SWEBENCH, ensure_dirs

API_ROOT = "https://api.github.com/repos/swe-bench/experiments/contents"
S3_BUCKET = "https://swe-bench-submissions.s3.amazonaws.com"
_S3_NS = {"s3": "http://s3.amazonaws.com/doc/2006-03-01/"}


def _headers() -> dict:
    h = {"Accept": "application/vnd.github+json", "User-Agent": "zest-demo"}
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


def _get(url: str, **kwargs):
    r = requests.get(url, headers=_headers(), timeout=60, **kwargs)
    if r.status_code == 403 and r.headers.get("X-RateLimit-Remaining") == "0":
        sys.exit(
            "GitHub API rate limit exhausted. Set a GITHUB_TOKEN environment "
            "variable (a free personal access token raises the limit to 5000/h) "
            "and retry."
        )
    return r


def list_submissions(split: str) -> list[str]:
    r = _get(f"{API_ROOT}/evaluation/{split}")
    r.raise_for_status()
    return sorted(e["name"] for e in r.json() if e["type"] == "dir")


def _list_dir(path: str) -> list[dict]:
    r = _get(f"{API_ROOT}/{path}")
    if r.status_code == 404:
        return []
    r.raise_for_status()
    entries = r.json()
    return entries if isinstance(entries, list) else []


def _download_file(entry: dict, dest_dir) -> None:
    dest = dest_dir / entry["name"]
    r = _get(entry["download_url"])
    r.raise_for_status()
    dest.write_bytes(r.content)


def _s3_list_trajs(split: str, submission: str, limit: int) -> list[str]:
    """Keys under the public S3 bucket's trajs/ prefix for this submission —
    used when the git repo has no trajs/ folder (the common case; most
    submissions only publish results/figures in-repo and keep trajectories
    in S3, per each submission's metadata.yaml `assets.trajs` field).
    max-keys=limit since a demo run only wants `limit` trajectories anyway."""
    prefix = f"{split}/{submission}/trajs/"
    url = f"{S3_BUCKET}/?list-type=2&prefix={prefix}&max-keys={limit}"
    r = requests.get(url, timeout=60)
    if not r.ok:
        return []
    root = ET.fromstring(r.text)
    return [k.text for k in root.findall("s3:Contents/s3:Key", _S3_NS) if k.text]


def _s3_download(key: str, dest_dir) -> str:
    name = key.rsplit("/", 1)[-1]
    r = requests.get(f"{S3_BUCKET}/{key}", timeout=60)
    r.raise_for_status()
    (dest_dir / name).write_bytes(r.content)
    return name


def fetch_results(split: str, submission: str, dest_dir) -> None:
    """Save results/results.json if present (tells us which tasks were resolved)."""
    for entry in _list_dir(f"evaluation/{split}/{submission}/results"):
        if entry["name"] == "results.json" and entry.get("download_url"):
            _download_file(entry, dest_dir)
            print("  saved results.json (resolved/unresolved outcomes)")
            return
    print("  no results/results.json found (outcomes will be unknown)")


def fetch_submission(split: str, submission: str, limit: int) -> None:
    ensure_dirs()
    dest_dir = RAW_SWEBENCH / submission
    trajs_dir = dest_dir / "trajs"
    trajs_dir.mkdir(parents=True, exist_ok=True)

    entries = _list_dir(f"evaluation/{split}/{submission}/trajs")
    if entries:
        files = [e for e in entries if e["type"] == "file" and e.get("download_url")]
        subdirs = [e for e in entries if e["type"] == "dir"]

        # some submissions nest one folder per instance; descend one level
        if not files and subdirs:
            for sub in subdirs[:limit]:
                inner = [
                    e
                    for e in _list_dir(f"evaluation/{split}/{submission}/trajs/{sub['name']}")
                    if e["type"] == "file" and e.get("download_url")
                ]
                inst_dir = trajs_dir / sub["name"]
                inst_dir.mkdir(exist_ok=True)
                for e in inner:
                    _download_file(e, inst_dir)
                print(f"  {sub['name']}/ ({len(inner)} files)")
        else:
            for e in files[:limit]:
                _download_file(e, trajs_dir)
                print(f"  {e['name']}")
    else:
        keys = _s3_list_trajs(split, submission, limit)
        if not keys:
            sys.exit(
                f"No trajectories found for '{submission}' ({split}) in the git repo "
                "or the public S3 bucket.\nPick another submission from --list."
            )
        for key in keys:
            name = _s3_download(key, trajs_dir)
            print(f"  {name}  (s3)")

    fetch_results(split, submission, dest_dir)

    manifest = {"split": split, "submission": submission, "limit": limit}
    (dest_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"\nDone -> {trajs_dir}")
    print("Next: python -m zest.parse --source swebench")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--list", action="store_true", help="list available submissions for the split")
    ap.add_argument("--split", default="verified", help="benchmark split: lite | verified | test (default: verified)")
    ap.add_argument("--submission", help="submission folder name to download trajs from")
    ap.add_argument("--limit", type=int, default=10, help="max trajectories to download (default: 10 — demo scale)")
    args = ap.parse_args()

    if args.list:
        for name in list_submissions(args.split):
            print(name)
        return
    if not args.submission:
        ap.error("either --list or --submission <name> is required")
    fetch_submission(args.split, args.submission, args.limit)


if __name__ == "__main__":
    main()
