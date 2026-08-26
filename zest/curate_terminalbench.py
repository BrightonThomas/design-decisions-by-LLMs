"""Build the final, analysis-ready Terminal-Bench datasets.

Policies:
* Terminal-Bench 2.0 keeps only usable trajectories with a known outcome.
* Terminal-Bench 2.1 keeps every local trajectory, adds only downloaded-only
  trajectories whose actual JSON body is available, and exposes
  ``resolved_available`` for missing outcomes.

Source downloads and files under ``data/normalized`` are never modified.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

from .augment_tbench20 import (
    DEFAULT_DEAD as TB20_BUILD_DEAD,
    DEFAULT_EXTERNAL_CSV as TB20_EXTERNAL_CSV,
    DEFAULT_EXTERNAL_TRAJECTORIES as TB20_EXTERNAL_TRAJECTORIES,
    DEFAULT_LOCAL as TB20_LOCAL,
    DEFAULT_SUMMARY as TB20_BUILD_SUMMARY,
    _external_metadata,
    _safe_external_path,
    build_augmented,
)
from .enrich_terminalbench_metadata import _parse_external_resolved, _trial_id
from .parse import atif_trajectory, is_atif


DEMO_ROOT = Path(__file__).resolve().parents[1]
THESIS_ROOT = DEMO_ROOT.parent

TB20_AUGMENTED = DEMO_ROOT / "data" / "curated" / ".build" / "tbench2.0_augmented.jsonl"
TB21_NORMALIZED = DEMO_ROOT / "data" / "normalized" / "tbench21.jsonl"
EXTERNAL_CSV = (
    THESIS_ROOT
    / "TerminalBenchAnalysis-main"
    / "data"
    / "processed_live"
    / "longitudinal"
    / "trajectory_longitudinal.csv"
)
TB21_EXTERNAL_TRAJECTORIES = (
    THESIS_ROOT
    / "TerminalBenchAnalysis-main"
    / "data"
    / "trajectories"
    / "terminal_bench_2_1"
)
CURATED_ROOT = DEMO_ROOT / "data" / "curated"
TB20_OUTPUT = CURATED_ROOT / "terminal_bench_2_0" / "trajectories.jsonl"
TB20_SUMMARY = CURATED_ROOT / "terminal_bench_2_0" / "summary.json"
TB21_OUTPUT = CURATED_ROOT / "terminal_bench_2_1" / "trajectories.jsonl"
TB21_SUMMARY = CURATED_ROOT / "terminal_bench_2_1" / "summary.json"


def _iter_jsonl(path: Path) -> Iterable[tuple[int, dict[str, Any]]]:
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if line.strip():
                yield line_number, json.loads(line)


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _load_external_tb21(path: Path) -> tuple[dict[str, dict[str, Any]], Counter[str]]:
    rows: dict[str, dict[str, Any]] = {}
    counts: Counter[str] = Counter()
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for raw in reader:
            if (raw.get("benchmark") or "").strip() != "terminal_bench_2_1":
                continue
            counts["downloaded_metadata_rows"] += 1
            trial_id = (raw.get("file_run_id") or "").strip()
            if not trial_id:
                counts["downloaded_rows_without_trial_id"] += 1
                continue
            if trial_id in rows:
                counts["duplicate_downloaded_trial_ids"] += 1
                continue
            resolved, inconsistent = _parse_external_resolved(raw)
            if inconsistent:
                counts["downloaded_outcome_field_conflicts"] += 1
            rows[trial_id] = {
                "trial_id": trial_id,
                "task_id": (
                    raw.get("task_name") or raw.get("task_id") or raw.get("file_task_id") or ""
                ).strip()
                or None,
                "resolved": resolved,
                "metadata": _external_metadata(raw),
            }
    return rows, counts


def curate_tb20(input_path: Path, output_path: Path, summary_path: Path) -> dict[str, Any]:
    counts: Counter[str] = Counter()
    seen: set[str] = set()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_suffix(output_path.suffix + ".tmp")

    with temporary.open("w", encoding="utf-8", newline="\n") as output:
        for _, trajectory in _iter_jsonl(input_path):
            counts["input_rows"] += 1
            resolved = trajectory.get("resolved")
            if resolved is None:
                counts["removed_missing_resolved"] += 1
                continue
            if resolved not in (True, False):
                counts["removed_invalid_resolved"] += 1
                continue
            if not trajectory.get("steps"):
                counts["removed_no_usable_steps"] += 1
                continue

            record_id = trajectory.get("id")
            if not record_id or record_id in seen:
                counts["removed_invalid_or_duplicate_id"] += 1
                continue
            seen.add(record_id)
            trajectory["resolved_available"] = True
            trajectory["trajectory_available"] = True
            counts["resolved_true" if resolved else "resolved_false"] += 1
            counts["output_rows"] += 1
            output.write(json.dumps(trajectory, ensure_ascii=False, separators=(",", ":")) + "\n")

    os.replace(temporary, output_path)
    summary = {
        "format_version": 1,
        "benchmark": "terminal_bench_2_0",
        "policy": "Keep only usable trajectories with resolved True or False.",
        "input": str(input_path),
        "output": str(output_path),
        "counts": dict(sorted(counts.items())),
    }
    _atomic_json(summary_path, summary)
    return summary


def _tb21_record(
    trajectory: dict[str, Any],
    trial_id: str,
    external: dict[str, Any] | None,
    origin: str,
    trajectory_available: bool,
) -> dict[str, Any]:
    local_resolved = trajectory.get("resolved")
    if local_resolved not in (True, False, None):
        local_resolved = None
    external_resolved = external.get("resolved") if external else None
    resolved = local_resolved if local_resolved is not None else external_resolved
    if local_resolved is not None:
        resolution_source = "normalized_original"
    elif external_resolved is not None:
        resolution_source = "downloaded_metadata"
    else:
        resolution_source = "not_available"

    trajectory["id"] = f"tbench21:{trial_id}"
    trajectory["trial_id"] = trial_id
    trajectory["resolved"] = resolved
    trajectory["resolved_available"] = resolved is not None
    trajectory["trajectory_available"] = trajectory_available
    meta = dict(trajectory.get("meta") or {})
    meta["data_origin"] = origin
    meta["resolution_source"] = resolution_source
    if external:
        meta["downloaded_metadata"] = external["metadata"]
    trajectory["meta"] = meta
    return trajectory


def curate_tb21(
    local_path: Path,
    external_csv: Path,
    external_trajectories: Path,
    output_path: Path,
    summary_path: Path,
) -> dict[str, Any]:
    external, counts = _load_external_tb21(external_csv)
    local_ids: set[str] = set()
    output_ids: set[str] = set()
    by_origin: Counter[str] = Counter()
    unparsed_reasons: Counter[str] = Counter()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_suffix(output_path.suffix + ".tmp")

    def write_record(output, record: dict[str, Any]) -> None:
        record_id = record["id"]
        if record_id in output_ids:
            raise ValueError(f"Duplicate TB 2.1 record id: {record_id}")
        output_ids.add(record_id)
        counts["output_rows"] += 1
        counts["resolved_available" if record["resolved_available"] else "resolved_not_available"] += 1
        counts["trajectory_available" if record["trajectory_available"] else "trajectory_not_available"] += 1
        if record.get("resolved") is True:
            counts["resolved_true"] += 1
        elif record.get("resolved") is False:
            counts["resolved_false"] += 1
        origin = (record.get("meta") or {}).get("data_origin") or "unknown"
        by_origin[origin] += 1
        output.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")

    with temporary.open("w", encoding="utf-8", newline="\n") as output:
        for line_number, trajectory in _iter_jsonl(local_path):
            counts["local_normalized_rows"] += 1
            trial_id, _ = _trial_id(trajectory.get("meta") or {})
            if not trial_id:
                trial_id = f"missing-line-{line_number}"
                counts["local_rows_without_trial_id"] += 1
            local_ids.add(trial_id)
            record = _tb21_record(
                trajectory,
                trial_id,
                external.get(trial_id),
                "local_normalized",
                bool(trajectory.get("steps")),
            )
            write_record(output, record)

        counts["downloaded_exact_overlaps"] = len(external.keys() & local_ids)
        candidates = [external[key] for key in sorted(external.keys() - local_ids)]
        counts["downloaded_candidates_to_add"] = len(candidates)

        for ext in candidates:
            trial_id = ext["trial_id"]
            raw_path = _safe_external_path(
                external_trajectories, ext["metadata"].get("rel_path")
            )
            reason: str | None = None
            raw: Any = None
            if raw_path is None:
                reason = "missing_or_unsafe_relative_path"
            elif not raw_path.is_file():
                reason = "trajectory_file_missing"
            else:
                try:
                    raw_text = raw_path.read_text(encoding="utf-8", errors="replace")
                    raw = json.loads(raw_text)
                except json.JSONDecodeError:
                    reason = (
                        "git_lfs_content_not_downloaded"
                        if raw_text.startswith("version https://git-lfs.github.com/spec/")
                        else "invalid_json"
                    )
                except OSError:
                    reason = "trajectory_file_unreadable"
            if reason is None and not is_atif(raw):
                reason = "not_atif"

            normalized = None
            if reason is None:
                normalized = atif_trajectory(raw, fallback_id=trial_id, source="tbench21")
                if normalized is None:
                    reason = "no_usable_agent_steps"

            if normalized is not None:
                trajectory = normalized.to_dict()
                trajectory["task_id"] = ext.get("task_id") or trajectory.get("task_id")
                if not trajectory.get("model"):
                    trajectory["model"] = ext["metadata"].get("model_name")
                trajectory.setdefault("meta", {})["file"] = raw_path.name
                origin = "downloaded_addition"
                available = True
                counts["downloaded_usable_additions"] += 1
            else:
                # A Git LFS pointer or otherwise unavailable body is not a
                # trajectory and therefore does not belong in the curated set.
                counts["downloaded_unavailable_skipped"] += 1
                unparsed_reasons[reason or "unknown"] += 1
                continue

            record = _tb21_record(
                trajectory, trial_id, ext, origin, available
            )
            write_record(output, record)

    os.replace(temporary, output_path)
    summary = {
        "format_version": 1,
        "benchmark": "terminal_bench_2_1",
        "policy": (
            "Retain every local trajectory and add downloaded-only rows only when "
            "their trajectory JSON is available. Use resolved_available for "
            "missing outcome data."
        ),
        "inputs": {
            "local_normalized": str(local_path),
            "downloaded_metadata": str(external_csv),
            "downloaded_trajectories": str(external_trajectories),
        },
        "output": str(output_path),
        "counts": dict(sorted(counts.items())),
        "by_origin": dict(sorted(by_origin.items())),
        "skipped_downloaded_unavailable": dict(sorted(unparsed_reasons.items())),
    }
    _atomic_json(summary_path, summary)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tb20-input", type=Path, default=TB20_AUGMENTED)
    parser.add_argument("--tb21-local", type=Path, default=TB21_NORMALIZED)
    parser.add_argument("--external-csv", type=Path, default=EXTERNAL_CSV)
    parser.add_argument(
        "--tb21-external-trajectories",
        type=Path,
        default=TB21_EXTERNAL_TRAJECTORIES,
    )
    parser.add_argument("--curated-root", type=Path, default=CURATED_ROOT)
    args = parser.parse_args()

    tb20_dir = args.curated_root / "terminal_bench_2_0"
    tb21_dir = args.curated_root / "terminal_bench_2_1"
    tb20_input = args.tb20_input
    generated_intermediate = False
    build_dir = args.curated_root / ".build"
    if not tb20_input.exists():
        # Rebuild the intermediate only when needed, then remove it below.
        build_dir.mkdir(parents=True, exist_ok=True)
        tb20_input = build_dir / "tbench2.0_augmented.jsonl"
        build_augmented(
            TB20_LOCAL,
            TB20_EXTERNAL_CSV,
            TB20_EXTERNAL_TRAJECTORIES,
            tb20_input,
            build_dir / TB20_BUILD_DEAD.name,
            build_dir / TB20_BUILD_SUMMARY.name,
        )
        generated_intermediate = True

    try:
        result = {
            "terminal_bench_2_0": curate_tb20(
                tb20_input,
                tb20_dir / "trajectories.jsonl",
                tb20_dir / "summary.json",
            ),
            "terminal_bench_2_1": curate_tb21(
                args.tb21_local,
                args.external_csv,
                args.tb21_external_trajectories,
                tb21_dir / "trajectories.jsonl",
                tb21_dir / "summary.json",
            ),
        }
    finally:
        if generated_intermediate:
            for path in build_dir.iterdir():
                if path.is_file():
                    path.unlink()
            build_dir.rmdir()
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
