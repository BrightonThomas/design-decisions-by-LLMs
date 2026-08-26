"""Build a metadata sidecar for normalized Terminal-Bench trajectories.

The normalized JSONL files are treated as immutable.  This module joins them
to the downloaded TerminalBenchAnalysis trajectory table by benchmark and raw
trial UUID, then writes one compact JSON object per normalized trajectory.

The sidecar keeps the original and external outcome values separately.  The
final ``resolved`` value only uses the external outcome when the normalized
trajectory has no outcome of its own; disagreements are explicitly flagged.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
from collections import Counter
from pathlib import Path
from typing import Any, Iterable


DEMO_ROOT = Path(__file__).resolve().parents[1]
THESIS_ROOT = DEMO_ROOT.parent

DEFAULT_EXTERNAL = (
    THESIS_ROOT
    / "TerminalBenchAnalysis-main"
    / "data"
    / "processed_live"
    / "longitudinal"
    / "trajectory_longitudinal.csv"
)
DEFAULT_BUILD_DIR = DEMO_ROOT / "data" / "curated" / ".build"
DEFAULT_OUTPUT = DEFAULT_BUILD_DIR / "terminalbench_metadata.jsonl"
DEFAULT_SUMMARY = DEFAULT_BUILD_DIR / "terminalbench_metadata_summary.json"

NORMALIZED_SOURCES = (
    ("tbench", "terminal_bench_2_0", DEMO_ROOT / "data" / "normalized" / "tbench.jsonl"),
    ("tbench21", "terminal_bench_2_1", DEMO_ROOT / "data" / "normalized" / "tbench21.jsonl"),
)


def _parse_number(value: Any) -> int | float | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        number = float(text)
    except ValueError:
        return None
    if number.is_integer():
        return int(number)
    return number


def _parse_external_resolved(row: dict[str, str]) -> tuple[bool | None, bool]:
    """Return (resolved, internally_inconsistent_external_fields)."""

    outcome_text = (row.get("reward_outcome") or "").strip().lower()
    outcome_value: bool | None
    if outcome_text == "pass":
        outcome_value = True
    elif outcome_text == "fail":
        outcome_value = False
    else:
        outcome_value = None

    passed_number = _parse_number(row.get("passed"))
    passed_value = None if passed_number is None else bool(passed_number >= 1)

    inconsistent = (
        outcome_value is not None
        and passed_value is not None
        and outcome_value != passed_value
    )
    return outcome_value if outcome_value is not None else passed_value, inconsistent


def _trial_id(meta: dict[str, Any]) -> tuple[str | None, str | None]:
    raw_file = meta.get("file")
    if not raw_file:
        return None, None
    name = Path(str(raw_file)).name
    stem = Path(name).stem
    if stem.endswith("-traj"):
        stem = stem[:-5]
    return stem or None, name


def _load_external_rows(
    path: Path,
) -> tuple[dict[tuple[str, str], dict[str, Any]], Counter[str]]:
    rows: dict[tuple[str, str], dict[str, Any]] = {}
    audit: Counter[str] = Counter()

    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {"benchmark", "file_run_id", "reward_outcome", "passed"}
        missing = required.difference(reader.fieldnames or [])
        if missing:
            raise ValueError(f"External metadata is missing required columns: {sorted(missing)}")

        for raw in reader:
            benchmark = (raw.get("benchmark") or "").strip()
            trial_id = (raw.get("file_run_id") or "").strip()
            if not benchmark or not trial_id:
                audit["external_rows_without_key"] += 1
                continue

            key = (benchmark, trial_id)
            if key in rows:
                audit["duplicate_external_keys"] += 1
                continue

            resolved, inconsistent = _parse_external_resolved(raw)
            if inconsistent:
                audit["external_outcome_field_conflicts"] += 1

            rows[key] = {
                "resolved": resolved,
                "reward": _parse_number(raw.get("reward")),
                "reward_outcome": (raw.get("reward_outcome") or "").strip() or None,
                "difficulty": (raw.get("difficulty") or "").strip() or None,
                "task_name": (raw.get("task_name") or "").strip() or None,
                "task_slug": (raw.get("task_slug") or "").strip() or None,
                "terminal_bench_task_name": (
                    raw.get("terminal_bench_task_name") or ""
                ).strip()
                or None,
                "category": (raw.get("category") or "").strip() or None,
                "tags": (raw.get("tags") or "").strip() or None,
                "prompt_tokens": _parse_number(raw.get("prompt_tokens")),
                "completion_tokens": _parse_number(raw.get("completion_tokens")),
                "total_tokens": _parse_number(raw.get("total_tokens")),
                "cost_usd": _parse_number(raw.get("cost_usd")),
                "duration_seconds": _parse_number(raw.get("duration_seconds")),
                "step_count": _parse_number(raw.get("step_count")),
                "tool_call_count": _parse_number(raw.get("tool_call_count")),
                "command_count": _parse_number(raw.get("command_count")),
                "scaffold": (raw.get("scaffold") or "").strip() or None,
                "model_name": (raw.get("model_name") or "").strip() or None,
                "agent_version": (raw.get("agent_version") or "").strip() or None,
                "rel_path": (raw.get("rel_path") or "").strip() or None,
            }
            audit[f"external_rows_{benchmark}"] += 1

    return rows, audit


def _iter_normalized(path: Path) -> Iterable[tuple[int, dict[str, Any]]]:
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if line.strip():
                yield line_number, json.loads(line)


def build_sidecar(external_path: Path, output_path: Path, summary_path: Path) -> dict[str, Any]:
    external, external_audit = _load_external_rows(external_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.parent.mkdir(parents=True, exist_ok=True)

    temp_output = output_path.with_suffix(output_path.suffix + ".tmp")
    seen_ids: set[str] = set()
    counts: Counter[str] = Counter(external_audit)
    by_source: dict[str, Counter[str]] = {source: Counter() for source, _, _ in NORMALIZED_SOURCES}

    with temp_output.open("w", encoding="utf-8", newline="\n") as out:
        for source, benchmark, normalized_path in NORMALIZED_SOURCES:
            source_counts = by_source[source]
            for line_number, trajectory in _iter_normalized(normalized_path):
                source_counts["normalized_rows"] += 1
                counts["normalized_rows"] += 1

                meta = trajectory.get("meta") or {}
                trial_id, raw_file = _trial_id(meta)
                if not trial_id:
                    source_counts["missing_trial_id"] += 1
                    counts["missing_trial_id"] += 1
                    trial_id = f"missing-line-{line_number}"

                record_id = f"{source}:{trial_id}"
                if record_id in seen_ids:
                    source_counts["duplicate_sidecar_ids"] += 1
                    counts["duplicate_sidecar_ids"] += 1
                seen_ids.add(record_id)

                external_row = external.get((benchmark, trial_id))
                external_resolved = external_row.get("resolved") if external_row else None
                original_resolved = trajectory.get("resolved")
                if original_resolved not in (True, False, None):
                    source_counts["invalid_original_resolved"] += 1
                    counts["invalid_original_resolved"] += 1
                    original_resolved = None

                conflict = (
                    original_resolved is not None
                    and external_resolved is not None
                    and original_resolved != external_resolved
                )

                if original_resolved is not None:
                    resolved = original_resolved
                    if external_resolved is None:
                        resolution_source = "normalized_original"
                    elif conflict:
                        resolution_source = "normalized_original_conflicts_external"
                    else:
                        resolution_source = "normalized_original_confirmed_external"
                elif external_resolved is not None:
                    resolved = external_resolved
                    resolution_source = "external_backfill"
                else:
                    resolved = None
                    resolution_source = "unresolved"

                if external_row:
                    source_counts["external_matches"] += 1
                    counts["external_matches"] += 1
                if conflict:
                    source_counts["outcome_conflicts"] += 1
                    counts["outcome_conflicts"] += 1
                if resolved is not None:
                    source_counts["resolved_final"] += 1
                    counts["resolved_final"] += 1
                else:
                    source_counts["unresolved_final"] += 1
                    counts["unresolved_final"] += 1
                source_counts[f"resolution_source_{resolution_source}"] += 1

                row = {
                    "id": record_id,
                    "trial_id": trial_id,
                    "source": source,
                    "benchmark": benchmark,
                    "normalized_file": normalized_path.name,
                    "normalized_line": line_number,
                    "raw_file": raw_file,
                    "task_id": trajectory.get("task_id"),
                    "agent": trajectory.get("agent"),
                    "model": trajectory.get("model"),
                    "original_resolved": original_resolved,
                    "external_resolved": external_resolved,
                    "resolved": resolved,
                    "resolution_source": resolution_source,
                    "outcome_conflict": conflict,
                    "external_match": external_row is not None,
                    "external_reward": external_row.get("reward") if external_row else None,
                    "external_reward_outcome": (
                        external_row.get("reward_outcome") if external_row else None
                    ),
                    "difficulty": external_row.get("difficulty") if external_row else None,
                    "external_task_name": external_row.get("task_name") if external_row else None,
                    "task_slug": external_row.get("task_slug") if external_row else None,
                    "terminal_bench_task_name": (
                        external_row.get("terminal_bench_task_name") if external_row else None
                    ),
                    "category": external_row.get("category") if external_row else None,
                    "tags": external_row.get("tags") if external_row else None,
                    "prompt_tokens": external_row.get("prompt_tokens") if external_row else None,
                    "completion_tokens": (
                        external_row.get("completion_tokens") if external_row else None
                    ),
                    "total_tokens": external_row.get("total_tokens") if external_row else None,
                    "cost_usd": external_row.get("cost_usd") if external_row else None,
                    "external_duration_seconds": (
                        external_row.get("duration_seconds") if external_row else None
                    ),
                    "local_duration_seconds": trajectory.get("duration_seconds"),
                    "local_step_count": len(trajectory.get("steps") or []),
                    "external_step_count": (
                        external_row.get("step_count") if external_row else None
                    ),
                    "external_tool_call_count": (
                        external_row.get("tool_call_count") if external_row else None
                    ),
                    "external_command_count": (
                        external_row.get("command_count") if external_row else None
                    ),
                    "external_scaffold": external_row.get("scaffold") if external_row else None,
                    "external_model_name": (
                        external_row.get("model_name") if external_row else None
                    ),
                    "external_agent_version": (
                        external_row.get("agent_version") if external_row else None
                    ),
                    "external_rel_path": external_row.get("rel_path") if external_row else None,
                }
                out.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")

    os.replace(temp_output, output_path)

    summary = {
        "format_version": 1,
        "output": str(output_path),
        "external_metadata": str(external_path),
        "join_key": ["benchmark", "trial_id"],
        "resolution_rule": (
            "Keep normalized resolved when present; otherwise backfill from external metadata. "
            "Flag disagreements without overwriting the normalized value."
        ),
        "counts": dict(sorted(counts.items())),
        "by_source": {
            source: dict(sorted(source_counts.items()))
            for source, source_counts in by_source.items()
        },
    }
    temp_summary = summary_path.with_suffix(summary_path.suffix + ".tmp")
    temp_summary.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    os.replace(temp_summary, summary_path)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--external", type=Path, default=DEFAULT_EXTERNAL)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--summary", type=Path, default=DEFAULT_SUMMARY)
    args = parser.parse_args()

    summary = build_sidecar(args.external, args.output, args.summary)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
