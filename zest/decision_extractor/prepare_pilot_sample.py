from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from .core import normalize_trajectory, read_jsonl, write_jsonl


# Ten distinct resolved tasks. The sample covers every TerminalBench 2.1
# harness and prioritises software-engineering and data-science tasks. The
# scheduler is retained as a calibration case for the current codebook.
PILOT_SPECS = (
    ("terminal-bench/fix-git", "mini-swe-agent", "muse-spark-1.1"),
    ("terminal-bench/pypi-server", "terminus-2", "gpt-5.5"),
    ("terminal-bench/cancel-async-tasks", "codex", "gpt-5.6-terra"),
    ("terminal-bench/git-leak-recovery", "claude-code", "claude-opus-4-8"),
    ("terminal-bench/kv-store-grpc", "cursor-cli", "grok-4.5"),
    (
        "terminal-bench/headless-terminal",
        "gemini-cli",
        "gemini-3.1-pro-preview",
    ),
    ("terminal-bench/mteb-retrieve", "cursor-cli", "grok-4.5"),
    (
        "terminal-bench/sam-cell-seg",
        "gemini-cli",
        "gemini-3.1-pro-preview-customtools",
    ),
    ("terminal-bench/query-optimize", "claude-code", "claude-sonnet-5"),
    (
        "terminal-bench/llm-inference-batching-scheduler",
        "claude-code",
        "claude-fable-5",
    ),
)


def harness_of(raw: dict[str, Any]) -> str:
    return str(raw.get("harness") or raw.get("agent") or "")


def canonical_model(value: Any) -> str:
    model = str(value or "")
    for prefix in ("anthropic/", "openai/", "gemini/", "vertex_ai/", "xai/", "cursor/"):
        if model.startswith(prefix):
            model = model[len(prefix) :]
    if model.endswith(":cloud"):
        model = model[: -len(":cloud")]
    return model


def downloaded_metadata(raw: dict[str, Any]) -> dict[str, Any]:
    return dict((raw.get("meta") or {}).get("downloaded_metadata") or {})


def select_pilot(input_path: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    wanted = set(PILOT_SPECS)
    candidates: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)

    for raw in read_jsonl(input_path):
        if raw.get("resolved") is not True:
            continue
        key = (str(raw.get("task_id") or ""), harness_of(raw), canonical_model(raw.get("model")))
        if key in wanted:
            candidates[key].append(raw)

    selected: list[dict[str, Any]] = []
    manifest: list[dict[str, Any]] = []
    for task_id, harness, model in PILOT_SPECS:
        key = (task_id, harness, model)
        rows = candidates.get(key, [])
        if not rows:
            raise ValueError(f"No resolved trajectory found for {key}")

        # Avoid an unusually short or long run when repeated trials are
        # available. Sorting makes selection deterministic across reruns.
        manageable = [row for row in rows if 8 <= len(row.get("steps") or []) <= 40]
        pool = manageable or rows
        pool.sort(key=lambda row: (len(row.get("steps") or []), str(row.get("trial_id") or "")))
        raw = pool[len(pool) // 2]
        trajectory = normalize_trajectory(raw)
        trajectory["model"] = canonical_model(trajectory.get("model"))
        metadata = downloaded_metadata(raw)
        trajectory.update(
            {
                "category": metadata.get("category"),
                "difficulty": metadata.get("difficulty"),
                "reported_total_tokens": metadata.get("total_tokens"),
            }
        )
        selected.append(trajectory)
        manifest.append(
            {
                "task_id": trajectory["task_id"],
                "trial_id": trajectory["trial_id"],
                "category": trajectory.get("category"),
                "difficulty": trajectory.get("difficulty"),
                "harness": trajectory.get("harness"),
                "model": trajectory.get("model"),
                "resolved": trajectory.get("resolved"),
                "steps": len(trajectory.get("steps") or []),
                "reported_total_tokens": trajectory.get("reported_total_tokens"),
            }
        )

    return selected, manifest


def write_manifest(rows: list[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prepare the ten-trajectory Month 3 pilot")
    parser.add_argument("--input", type=Path, required=True, help="Curated TerminalBench 2.1 JSONL")
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    trajectories, manifest = select_pilot(args.input)
    trajectory_path = args.output_dir / "pilot_trajectories_10.jsonl"
    manifest_path = args.output_dir / "pilot_manifest.csv"
    count = write_jsonl(trajectories, trajectory_path)
    write_manifest(manifest, manifest_path)
    print(
        json.dumps(
            {
                "trajectories": count,
                "unique_tasks": len({row["task_id"] for row in manifest}),
                "categories": sorted({str(row["category"]) for row in manifest}),
                "harnesses": sorted({str(row["harness"]) for row in manifest}),
                "trajectory_file": str(trajectory_path),
                "manifest_file": str(manifest_path),
            }
        )
    )


if __name__ == "__main__":
    main()
