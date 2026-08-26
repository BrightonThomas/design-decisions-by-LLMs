"""Stream a small sample of the MOSAIC dataset (real-world coding-agent
pull requests) from HuggingFace.

Source: AISE-TUDelft/MOSAIC-agentic-3m (~110k agent PRs with commits,
reviews, comments; agents incl. Codex, Claude Code, Copilot, Jules, Devin).

Uses streaming mode — nothing close to the full dataset is downloaded,
only the first N rows are pulled and written to a local JSONL file.

Demo scale: default limit 200 rows.

Usage:
    python -m zest.fetch_mosaic
    python -m zest.fetch_mosaic --limit 200 --config <name> --split train
"""

from __future__ import annotations

import argparse
import itertools
import json

from .paths import RAW_MOSAIC, ensure_dirs, replace_with_retry

REPO_ID = "AISE-TUDelft/MOSAIC-agentic-3m"


def fetch(limit: int, config: str | None, split: str) -> None:
    from datasets import load_dataset  # deferred: heavy import

    ensure_dirs()
    try:
        ds = load_dataset(REPO_ID, name=config, split=split, streaming=True)
    except Exception as e:
        print(f"load_dataset failed: {e}\n")
        _print_configs()
        raise SystemExit(1)

    # Config name is the only place agent identity lives (e.g.
    # "PullRequests_Claude") -- rows carry no agent field, just the
    # human/bot GitHub author of the PR. One file per config, named after
    # it, so parse_mosaic can recover the agent and multiple configs can
    # coexist without overwriting each other.
    out = RAW_MOSAIC / f"{config or 'sample'}.jsonl"
    tmp = out.with_suffix(out.suffix + ".tmp")
    n = 0
    with open(tmp, "w", encoding="utf-8") as f:
        for row in itertools.islice(iter(ds), limit):
            f.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
            n += 1
    replace_with_retry(tmp, out)
    print(f"Wrote {n} rows -> {out}")
    print("Next: python -m zest.parse --source mosaic")


def _print_configs() -> None:
    try:
        from datasets import get_dataset_config_names, get_dataset_split_names

        configs = get_dataset_config_names(REPO_ID)
        print(f"Available configs: {configs}")
        for c in configs[:3]:
            print(f"  splits[{c}]: {get_dataset_split_names(REPO_ID, c)}")
        print("Retry with --config <name> and/or --split <name>.")
    except Exception as e:  # noqa: BLE001 - purely diagnostic
        print(f"(could not enumerate configs either: {e})")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--limit", type=int, default=200, help="rows to stream (default: 200 — demo scale)")
    ap.add_argument("--config", default=None, help="dataset config name, if the default fails")
    ap.add_argument("--split", default="train", help="dataset split (default: train)")
    args = ap.parse_args()
    fetch(args.limit, args.config, args.split)


if __name__ == "__main__":
    main()
