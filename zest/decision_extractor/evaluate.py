from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from . import EVALUATOR_VERSION
from .core import read_jsonl


def step_overlap(left: dict[str, Any], right: dict[str, Any]) -> float:
    a = set(left.get("source_steps") or [])
    b = set(right.get("source_steps") or [])
    if not a or not b:
        return 0.0
    return len(a & b) / min(len(a), len(b))


def flatten_gold(records: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        if "events" in record:
            grouped[str(record["trial_id"])].extend(record["events"])
        else:
            grouped[str(record["trial_id"])].append(record)
    return grouped


def flatten_predictions(records: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        extraction = record.get("extraction")
        if isinstance(extraction, dict) and isinstance(extraction.get("events"), list):
            grouped[str(record["trial_id"])].extend(extraction["events"])
    return grouped


def match_events(
    gold: list[dict[str, Any]], predicted: list[dict[str, Any]], threshold: float
) -> tuple[list[tuple[int, int, float]], list[int], list[int]]:
    candidates = []
    for gi, gold_event in enumerate(gold):
        for pi, predicted_event in enumerate(predicted):
            overlap = step_overlap(gold_event, predicted_event)
            if overlap >= threshold:
                category_bonus = 1 if gold_event.get("primary_category") == predicted_event.get("primary_category") else 0
                candidates.append((overlap, category_bonus, gi, pi))
    candidates.sort(reverse=True)
    used_gold: set[int] = set()
    used_predicted: set[int] = set()
    matches: list[tuple[int, int, float]] = []
    for overlap, _, gi, pi in candidates:
        if gi not in used_gold and pi not in used_predicted:
            used_gold.add(gi)
            used_predicted.add(pi)
            matches.append((gi, pi, overlap))
    return (
        matches,
        [i for i in range(len(gold)) if i not in used_gold],
        [i for i in range(len(predicted)) if i not in used_predicted],
    )


def safe_ratio(numerator: int | float, denominator: int | float) -> float | None:
    return numerator / denominator if denominator else None


def evaluate_records(
    gold_records: list[dict[str, Any]],
    prediction_records: list[dict[str, Any]],
    threshold: float = 0.5,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    gold_by_trial = flatten_gold(gold_records)
    pred_by_trial = flatten_predictions(prediction_records)
    error_rows: list[dict[str, Any]] = []
    match_rows: list[dict[str, Any]] = []
    tp = fp = fn = 0
    field_hits = Counter()
    matched_count = 0
    overlap_sum = 0.0

    for trial_id in sorted(set(gold_by_trial) | set(pred_by_trial)):
        gold = gold_by_trial.get(trial_id, [])
        predicted = pred_by_trial.get(trial_id, [])
        matches, missed_gold, extra_predicted = match_events(gold, predicted, threshold)
        tp += len(matches)
        fn += len(missed_gold)
        fp += len(extra_predicted)
        for gi, pi, overlap in matches:
            g, p = gold[gi], predicted[pi]
            matched_count += 1
            overlap_sum += overlap
            row = {
                "trial_id": trial_id,
                "gold_event_id": g.get("event_id"),
                "predicted_event_id": p.get("event_id"),
                "step_overlap": round(overlap, 4),
                "gold_steps": g.get("source_steps"),
                "predicted_steps": p.get("source_steps"),
                "gold_category": g.get("primary_category"),
                "predicted_category": p.get("primary_category"),
                "gold_reason_visibility": g.get("reason_visibility"),
                "predicted_reason_visibility": p.get("reason_visibility"),
                "gold_primary_reason": g.get("primary_reason"),
                "predicted_primary_reason": p.get("primary_reason"),
            }
            match_rows.append(row)
            comparisons = {
                "category": g.get("primary_category") == p.get("primary_category"),
                "reason_visibility": g.get("reason_visibility") == p.get("reason_visibility"),
                "primary_reason": g.get("primary_reason") == p.get("primary_reason"),
                "exact_boundary": set(g.get("source_steps") or []) == set(p.get("source_steps") or []),
            }
            for field, hit in comparisons.items():
                field_hits[field] += int(hit)
                if not hit:
                    error_rows.append({
                        "trial_id": trial_id,
                        "error_type": f"wrong_{field}",
                        "gold_event_id": g.get("event_id"),
                        "predicted_event_id": p.get("event_id"),
                        "gold_value": row.get(f"gold_{field}", g.get("source_steps")),
                        "predicted_value": row.get(f"predicted_{field}", p.get("source_steps")),
                        "step_overlap": round(overlap, 4),
                    })
        for gi in missed_gold:
            g = gold[gi]
            error_rows.append({
                "trial_id": trial_id,
                "error_type": "missed_decision",
                "gold_event_id": g.get("event_id"),
                "predicted_event_id": None,
                "gold_value": g.get("primary_category"),
                "predicted_value": None,
                "step_overlap": 0.0,
            })
        for pi in extra_predicted:
            p = predicted[pi]
            error_rows.append({
                "trial_id": trial_id,
                "error_type": "false_positive",
                "gold_event_id": None,
                "predicted_event_id": p.get("event_id"),
                "gold_value": None,
                "predicted_value": p.get("primary_category"),
                "step_overlap": 0.0,
            })

    precision = safe_ratio(tp, tp + fp)
    recall = safe_ratio(tp, tp + fn)
    f1 = None if precision is None or recall is None or precision + recall == 0 else 2 * precision * recall / (precision + recall)
    invalid_records = sum(not record.get("valid", False) for record in prediction_records)
    validation_errors = Counter(
        error.get("code")
        for record in prediction_records
        for error in record.get("errors", [])
        if error.get("code")
    )
    summary = {
        "evaluator_version": EVALUATOR_VERSION,
        "match_threshold": threshold,
        "gold_events": sum(len(v) for v in gold_by_trial.values()),
        "predicted_events": sum(len(v) for v in pred_by_trial.values()),
        "true_positive_events": tp,
        "false_positive_events": fp,
        "missed_events": fn,
        "event_precision": precision,
        "event_recall": recall,
        "event_f1": f1,
        "mean_matched_step_overlap": safe_ratio(overlap_sum, matched_count),
        "category_accuracy_on_matches": safe_ratio(field_hits["category"], matched_count),
        "reason_visibility_accuracy_on_matches": safe_ratio(field_hits["reason_visibility"], matched_count),
        "primary_reason_accuracy_on_matches": safe_ratio(field_hits["primary_reason"], matched_count),
        "exact_boundary_accuracy_on_matches": safe_ratio(field_hits["exact_boundary"], matched_count),
        "prediction_records": len(prediction_records),
        "invalid_prediction_records": invalid_records,
        "validation_error_counts": dict(validation_errors),
        "error_type_counts": dict(Counter(row["error_type"] for row in error_rows)),
    }
    return summary, match_rows, error_rows


def write_csv(rows: list[dict[str, Any]], path: Path, default_fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = list(rows[0]) if rows else default_fields
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate extracted decisions against gold")
    parser.add_argument("--gold", type=Path, required=True)
    parser.add_argument("--predictions", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--matches", type=Path, required=True)
    parser.add_argument("--errors", type=Path, required=True)
    parser.add_argument("--threshold", type=float, default=0.5)
    parser.add_argument("--trial-id", action="append", default=[])
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    gold_records = list(read_jsonl(args.gold))
    prediction_records = list(read_jsonl(args.predictions))
    if args.trial_id:
        selected = set(args.trial_id)
        gold_records = [record for record in gold_records if str(record.get("trial_id")) in selected]
        prediction_records = [record for record in prediction_records if str(record.get("trial_id")) in selected]
    summary, matches, errors = evaluate_records(gold_records, prediction_records, args.threshold)
    args.summary.parent.mkdir(parents=True, exist_ok=True)
    args.summary.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    write_csv(matches, args.matches, [
        "trial_id", "gold_event_id", "predicted_event_id", "step_overlap",
        "gold_steps", "predicted_steps", "gold_category", "predicted_category",
        "gold_reason_visibility", "predicted_reason_visibility",
        "gold_primary_reason", "predicted_primary_reason",
    ])
    write_csv(errors, args.errors, [
        "trial_id", "error_type", "gold_event_id", "predicted_event_id",
        "gold_value", "predicted_value", "step_overlap",
    ])
    print(json.dumps(summary))


if __name__ == "__main__":
    main()
