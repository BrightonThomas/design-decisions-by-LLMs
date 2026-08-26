"""Create an augmented Terminal-Bench 2.0 normalized dataset.

The original ``data/normalized/tbench.jsonl`` file is never modified.  The
output contains every local normalized trajectory plus downloaded trajectories
whose trial UUID is not already present locally.  Outcomes from the downloaded
metadata fill only missing ``resolved`` values; known local outcomes win and
any disagreement is counted.

Downloaded rows whose trajectory body cannot be converted into at least one
usable normalized agent step are written to a separate dead-records JSONL file.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

from .enrich_terminalbench_metadata import _parse_external_resolved, _parse_number, _trial_id
from .parse import atif_trajectory, is_atif


DEMO_ROOT = Path(__file__).resolve().parents[1]
THESIS_ROOT = DEMO_ROOT.parent

DEFAULT_LOCAL = DEMO_ROOT / "data" / "normalized" / "tbench.jsonl"
DEFAULT_EXTERNAL_CSV = (
    THESIS_ROOT
    / "TerminalBenchAnalysis-main"
    / "data"
    / "processed_live"
    / "longitudinal"
    / "trajectory_longitudinal.csv"
)
DEFAULT_EXTERNAL_TRAJECTORIES = (
    THESIS_ROOT
    / "TerminalBenchAnalysis-main"
    / "data"
    / "trajectories"
    / "terminal_bench_2_0"
)
DEFAULT_BUILD_DIR = DEMO_ROOT / "data" / "curated" / ".build"
DEFAULT_OUTPUT = DEFAULT_BUILD_DIR / "tbench2.0_augmented.jsonl"
DEFAULT_DEAD = DEFAULT_BUILD_DIR / "tbench2.0_dead_data.jsonl"
DEFAULT_SUMMARY = DEFAULT_BUILD_DIR / "tbench2.0_augmentation_summary.json"

BENCHMARK = "terminal_bench_2_0"


def _iter_jsonl(path: Path) -> Iterable[tuple[int, dict[str, Any]]]:
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if line.strip():
                yield line_number, json.loads(line)


def _external_metadata(row: dict[str, str]) -> dict[str, Any]:
    """Keep analysis-relevant metadata without copying long text fields."""

    return {
        "reward": _parse_number(row.get("reward")),
        "reward_outcome": (row.get("reward_outcome") or "").strip() or None,
        "difficulty": (row.get("difficulty") or "").strip() or None,
        "task_name": (row.get("task_name") or "").strip() or None,
        "task_slug": (row.get("task_slug") or "").strip() or None,
        "terminal_bench_task_name": (
            row.get("terminal_bench_task_name") or ""
        ).strip()
        or None,
        "category": (row.get("category") or "").strip() or None,
        "tags": (row.get("tags") or "").strip() or None,
        "prompt_tokens": _parse_number(row.get("prompt_tokens")),
        "completion_tokens": _parse_number(row.get("completion_tokens")),
        "total_tokens": _parse_number(row.get("total_tokens")),
        "cost_usd": _parse_number(row.get("cost_usd")),
        "duration_seconds": _parse_number(row.get("duration_seconds")),
        "step_count": _parse_number(row.get("step_count")),
        "tool_call_count": _parse_number(row.get("tool_call_count")),
        "command_count": _parse_number(row.get("command_count")),
        "scaffold": (row.get("scaffold") or "").strip() or None,
        "model_name": (row.get("model_name") or "").strip() or None,
        "agent_version": (row.get("agent_version") or "").strip() or None,
        "original_format": (row.get("original_format") or "").strip() or None,
        "rel_path": (row.get("rel_path") or "").strip() or None,
    }


def _load_external(path: Path) -> tuple[dict[str, dict[str, Any]], Counter[str]]:
    rows: dict[str, dict[str, Any]] = {}
    counts: Counter[str] = Counter()

    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {"benchmark", "file_run_id", "rel_path", "reward_outcome", "passed"}
        missing = required.difference(reader.fieldnames or [])
        if missing:
            raise ValueError(f"External metadata is missing columns: {sorted(missing)}")

        for raw in reader:
            if (raw.get("benchmark") or "").strip() != BENCHMARK:
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
            if resolved is None:
                counts["downloaded_rows_without_resolved"] += 1

            rows[trial_id] = {
                "trial_id": trial_id,
                "task_id": (raw.get("task_id") or raw.get("file_task_id") or "").strip()
                or None,
                "resolved": resolved,
                "metadata": _external_metadata(raw),
            }

    return rows, counts


def _set_common_fields(
    trajectory: dict[str, Any],
    trial_id: str,
    origin: str,
    resolution_source: str,
    external: dict[str, Any] | None,
) -> dict[str, Any]:
    trajectory["id"] = f"tbench:{trial_id}"
    trajectory["trial_id"] = trial_id
    meta = dict(trajectory.get("meta") or {})
    meta["data_origin"] = origin
    meta["resolution_source"] = resolution_source
    if external is not None:
        meta["downloaded_metadata"] = external["metadata"]
    trajectory["meta"] = meta
    return trajectory


def _safe_external_path(base: Path, rel_path: str | None) -> Path | None:
    if not rel_path:
        return None
    base_resolved = base.resolve()
    candidate = (base / Path(rel_path)).resolve()
    try:
        candidate.relative_to(base_resolved)
    except ValueError:
        return None
    return candidate


def _dead_record(external: dict[str, Any], reason: str) -> dict[str, Any]:
    trial_id = external["trial_id"]
    return {
        "id": f"tbench:{trial_id}",
        "trial_id": trial_id,
        "task_id": external.get("task_id"),
        "reason": reason,
        "external_resolved": external.get("resolved"),
        "downloaded_metadata": external.get("metadata"),
    }


def build_augmented(
    local_path: Path,
    external_csv: Path,
    external_trajectories: Path,
    output_path: Path,
    dead_path: Path,
    summary_path: Path,
) -> dict[str, Any]:
    external, counts = _load_external(external_csv)
    by_dead_reason: Counter[str] = Counter()
    by_dead_scaffold: Counter[str] = Counter()
    by_added_scaffold: Counter[str] = Counter()
    local_ids: set[str] = set()
    output_ids: set[str] = set()
    dead_records: list[dict[str, Any]] = []

    output_path.parent.mkdir(parents=True, exist_ok=True)
    dead_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    output_tmp = output_path.with_suffix(output_path.suffix + ".tmp")

    with output_tmp.open("w", encoding="utf-8", newline="\n") as output:
        for line_number, trajectory in _iter_jsonl(local_path):
            counts["local_normalized_rows"] += 1
            trial_id, _ = _trial_id(trajectory.get("meta") or {})
            if not trial_id:
                counts["local_rows_without_trial_id"] += 1
                trial_id = f"missing-line-{line_number}"
            if trial_id in local_ids:
                counts["duplicate_local_trial_ids"] += 1
            local_ids.add(trial_id)

            ext = external.get(trial_id)
            local_resolved = trajectory.get("resolved")
            if local_resolved not in (True, False, None):
                counts["invalid_local_resolved"] += 1
                local_resolved = None
            if local_resolved is None:
                counts["local_rows_unresolved_before_backfill"] += 1

            ext_resolved = ext.get("resolved") if ext else None
            conflict = (
                local_resolved is not None
                and ext_resolved is not None
                and local_resolved != ext_resolved
            )
            if conflict:
                counts["local_external_outcome_conflicts"] += 1

            if local_resolved is not None:
                final_resolved = local_resolved
                resolution_source = (
                    "normalized_original_conflicts_external"
                    if conflict
                    else "normalized_original_confirmed_external"
                    if ext_resolved is not None
                    else "normalized_original"
                )
            elif ext_resolved is not None:
                final_resolved = ext_resolved
                resolution_source = "external_backfill"
                counts["local_rows_backfilled_from_download"] += 1
            else:
                final_resolved = None
                resolution_source = "unresolved"

            trajectory["resolved"] = final_resolved
            trajectory = _set_common_fields(
                trajectory,
                trial_id,
                "local_normalized",
                resolution_source,
                ext,
            )
            record_id = trajectory["id"]
            output_ids.add(record_id)
            output.write(json.dumps(trajectory, ensure_ascii=False, separators=(",", ":")) + "\n")

        candidates = [external[key] for key in sorted(external.keys() - local_ids)]
        counts["downloaded_exact_overlaps"] = len(external.keys() & local_ids)
        counts["downloaded_candidates_to_add"] = len(candidates)

        for ext in candidates:
            trial_id = ext["trial_id"]
            rel_path = ext["metadata"].get("rel_path")
            raw_path = _safe_external_path(external_trajectories, rel_path)
            reason: str | None = None
            raw: Any = None

            if raw_path is None:
                reason = "missing_or_unsafe_relative_path"
            elif not raw_path.is_file():
                reason = "trajectory_file_missing"
            else:
                try:
                    raw = json.loads(raw_path.read_text(encoding="utf-8", errors="replace"))
                except json.JSONDecodeError:
                    reason = "invalid_json"
                except OSError:
                    reason = "trajectory_file_unreadable"

            if reason is None and not is_atif(raw):
                reason = "not_atif"

            normalized = None
            if reason is None:
                normalized = atif_trajectory(raw, fallback_id=trial_id, source="tbench")
                if normalized is None:
                    reason = "no_usable_agent_steps"

            if reason is not None:
                counts["dead_downloaded_candidates"] += 1
                by_dead_reason[reason] += 1
                dead_scaffold = ext["metadata"].get("scaffold") or "unknown"
                by_dead_scaffold[dead_scaffold] += 1
                if ext.get("resolved") is None:
                    counts["dead_rows_without_resolved"] += 1
                else:
                    counts["dead_rows_with_resolved"] += 1
                dead_records.append(_dead_record(ext, reason))
                continue

            trajectory = normalized.to_dict()
            trajectory["task_id"] = ext.get("task_id") or trajectory.get("task_id")
            trajectory["resolved"] = ext.get("resolved")
            if not trajectory.get("model"):
                trajectory["model"] = ext["metadata"].get("model_name")
            if raw_path is not None:
                trajectory.setdefault("meta", {})["file"] = raw_path.name
            resolution_source = (
                "external_downloaded_addition"
                if ext.get("resolved") is not None
                else "unresolved_downloaded_addition"
            )
            trajectory = _set_common_fields(
                trajectory,
                trial_id,
                "downloaded_addition",
                resolution_source,
                ext,
            )
            record_id = trajectory["id"]
            if record_id in output_ids:
                counts["duplicate_augmented_ids"] += 1
                dead_records.append(_dead_record(ext, "duplicate_augmented_id"))
                by_dead_reason["duplicate_augmented_id"] += 1
                dead_scaffold = ext["metadata"].get("scaffold") or "unknown"
                by_dead_scaffold[dead_scaffold] += 1
                if ext.get("resolved") is None:
                    counts["dead_rows_without_resolved"] += 1
                else:
                    counts["dead_rows_with_resolved"] += 1
                counts["dead_downloaded_candidates"] += 1
                continue
            output_ids.add(record_id)
            counts["added_usable_rows"] += 1
            scaffold = ext["metadata"].get("scaffold") or "unknown"
            by_added_scaffold[scaffold] += 1
            output.write(json.dumps(trajectory, ensure_ascii=False, separators=(",", ":")) + "\n")

    os.replace(output_tmp, output_path)

    dead_tmp = dead_path.with_suffix(dead_path.suffix + ".tmp")
    with dead_tmp.open("w", encoding="utf-8", newline="\n") as dead_output:
        for record in dead_records:
            dead_output.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
    os.replace(dead_tmp, dead_path)

    # Validate final outcome and origin counts from the actual written artifact.
    final_counts: Counter[str] = Counter()
    seen: set[str] = set()
    for _, record in _iter_jsonl(output_path):
        record_id = record.get("id")
        if not record_id or record_id in seen:
            final_counts["invalid_or_duplicate_ids"] += 1
        seen.add(record_id)
        resolved = record.get("resolved")
        if resolved is True:
            final_counts["resolved_true"] += 1
        elif resolved is False:
            final_counts["resolved_false"] += 1
        elif resolved is None:
            final_counts["resolved_missing"] += 1
        else:
            final_counts["resolved_invalid_type"] += 1
        origin = (record.get("meta") or {}).get("data_origin") or "unknown"
        final_counts[f"origin_{origin}"] += 1

    final_counts["augmented_rows"] = sum(
        final_counts[key]
        for key in ("resolved_true", "resolved_false", "resolved_missing", "resolved_invalid_type")
    )
    final_counts["resolved_available"] = (
        final_counts["resolved_true"] + final_counts["resolved_false"]
    )
    counts.update(final_counts)

    summary = {
        "format_version": 1,
        "benchmark": BENCHMARK,
        "inputs": {
            "local_normalized": str(local_path),
            "downloaded_metadata": str(external_csv),
            "downloaded_trajectories": str(external_trajectories),
        },
        "outputs": {
            "augmented_jsonl": str(output_path),
            "dead_data_jsonl": str(dead_path),
        },
        "rules": {
            "join_key": "trial UUID (local meta.file stem vs downloaded file_run_id)",
            "resolved": (
                "Keep a known local resolved value; otherwise fill from downloaded "
                "reward_outcome/passed metadata."
            ),
            "dead_data": (
                "Downloaded candidate absent from the local normalized data whose body "
                "cannot be parsed into at least one usable normalized agent step."
            ),
            "resolved_missing": "Usable augmented row whose final resolved value is null.",
        },
        "counts": dict(sorted(counts.items())),
        "dead_by_reason": dict(sorted(by_dead_reason.items())),
        "dead_by_scaffold": dict(sorted(by_dead_scaffold.items())),
        "added_by_scaffold": dict(sorted(by_added_scaffold.items())),
    }
    summary_tmp = summary_path.with_suffix(summary_path.suffix + ".tmp")
    summary_tmp.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    os.replace(summary_tmp, summary_path)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--local", type=Path, default=DEFAULT_LOCAL)
    parser.add_argument("--external-csv", type=Path, default=DEFAULT_EXTERNAL_CSV)
    parser.add_argument(
        "--external-trajectories", type=Path, default=DEFAULT_EXTERNAL_TRAJECTORIES
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--dead", type=Path, default=DEFAULT_DEAD)
    parser.add_argument("--summary", type=Path, default=DEFAULT_SUMMARY)
    args = parser.parse_args()

    summary = build_augmented(
        args.local,
        args.external_csv,
        args.external_trajectories,
        args.output,
        args.dead,
        args.summary,
    )
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
