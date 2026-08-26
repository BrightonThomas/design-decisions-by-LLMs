from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Iterable, Iterator

from . import SCHEMA_VERSION


CATEGORIES = {f"D{i}" for i in range(1, 9)}
REASONS = {f"R{i}" for i in range(9)}
DECISION_VISIBILITY = {"STATED", "BEHAVIOURAL", "AMBIGUOUS"}
REASON_VISIBILITY = {"EXPLICIT", "CONTEXTUAL", "UNAVAILABLE"}
CONFIDENCE = {"HIGH", "MEDIUM", "LOW"}
EVIDENCE_FIELDS = {"thought", "action", "observation"}


def read_jsonl(path: Path) -> Iterator[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if line.strip():
                try:
                    yield json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ValueError(f"Invalid JSON at {path}:{line_number}: {exc}") from exc


def write_jsonl(records: Iterable[dict[str, Any]], path: Path) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
            count += 1
    return count


def trial_id_of(trajectory: dict[str, Any]) -> str:
    meta = trajectory.get("meta") or {}
    candidates = (
        trajectory.get("trial_id"), meta.get("trial_id"), meta.get("run_id"),
        meta.get("trial_name"), meta.get("uuid"), meta.get("id"),
    )
    for value in candidates:
        if value:
            return str(value)
    raise ValueError("Trajectory has no trial identifier")


def normalize_trajectory(raw: dict[str, Any]) -> dict[str, Any]:
    """Return the small, stable representation sent to an extractor."""
    meta = raw.get("meta") or {}
    steps = []
    for position, raw_step in enumerate(raw.get("steps") or []):
        step_id = raw_step.get("index", raw_step.get("step", position))
        steps.append({
            "step": int(step_id),
            "thought": raw_step.get("thought"),
            "action": raw_step.get("action"),
            "observation": raw_step.get("observation"),
        })
    return {
        "task_id": str(raw.get("task_id") or meta.get("task_id") or ""),
        "trial_id": trial_id_of(raw),
        "model": raw.get("model"),
        "harness": raw.get("harness") or raw.get("agent"),
        "resolved": raw.get("resolved"),
        "task_description": (
            raw.get("task_description") or meta.get("task_description") or
            meta.get("task_prompt") or meta.get("instruction")
        ),
        "steps": steps,
    }


def select_trajectories(
    input_path: Path,
    task_id: str | None = None,
    trial_ids: set[str] | None = None,
    resolved_only: bool = False,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    for raw in read_jsonl(input_path):
        if task_id and raw.get("task_id") != task_id:
            continue
        if resolved_only and raw.get("resolved") is not True:
            continue
        try:
            trajectory = normalize_trajectory(raw)
        except ValueError:
            continue
        if trial_ids and trajectory["trial_id"] not in trial_ids:
            continue
        selected.append(trajectory)
        if limit is not None and len(selected) >= limit:
            break
    return selected


def strip_json_fence(text: str) -> str:
    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped
    lines = stripped.splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip()


def parse_response(text: str) -> dict[str, Any]:
    value = json.loads(strip_json_fence(text))
    if not isinstance(value, dict):
        raise ValueError("Extractor response must be a JSON object")
    return value


def validate_extraction(
    extraction: dict[str, Any], trajectory: dict[str, Any]
) -> list[dict[str, Any]]:
    """Validate schema rules and ensure evidence really occurs in the trajectory."""
    errors: list[dict[str, Any]] = []

    def add(code: str, path: str, message: str) -> None:
        errors.append({"code": code, "path": path, "message": message})

    allowed_top = {"schema_version", "task_id", "trial_id", "events"}
    missing = allowed_top - extraction.keys()
    extra = extraction.keys() - allowed_top
    for key in sorted(missing):
        add("missing_field", key, "Required top-level field is missing")
    for key in sorted(extra):
        add("extra_field", key, "Unexpected top-level field")
    if extraction.get("schema_version") != SCHEMA_VERSION:
        add("schema_version", "schema_version", f"Expected {SCHEMA_VERSION}")
    if extraction.get("task_id") != trajectory.get("task_id"):
        add("identity_mismatch", "task_id", "Does not match source trajectory")
    if extraction.get("trial_id") != trajectory.get("trial_id"):
        add("identity_mismatch", "trial_id", "Does not match source trajectory")
    events = extraction.get("events")
    if not isinstance(events, list):
        add("type_error", "events", "Must be a list")
        return errors

    source_by_step = {step["step"]: step for step in trajectory.get("steps", [])}
    seen_event_ids: set[str] = set()
    event_fields = {
        "event_id", "source_steps", "primary_category", "secondary_category",
        "decision_summary", "selected_option", "alternative_visible",
        "primary_reason", "secondary_reasons", "reason_summary",
        "decision_visibility", "reason_visibility", "confidence", "evidence",
    }
    for i, event in enumerate(events):
        base = f"events[{i}]"
        if not isinstance(event, dict):
            add("type_error", base, "Event must be an object")
            continue
        for key in sorted(event_fields - event.keys()):
            add("missing_field", f"{base}.{key}", "Required event field is missing")
        for key in sorted(event.keys() - event_fields):
            add("extra_field", f"{base}.{key}", "Unexpected event field")
        event_id = event.get("event_id")
        if not isinstance(event_id, str) or re.fullmatch(r"P\d{2,}", event_id) is None:
            add("invalid_event_id", f"{base}.event_id", "Expected P01, P02, ...")
        elif event_id != f"P{i + 1:02d}":
            add("invalid_event_id", f"{base}.event_id", "Event IDs must be consecutive and chronological")
        elif event_id in seen_event_ids:
            add("duplicate_event_id", f"{base}.event_id", "Event ID is repeated")
        else:
            seen_event_ids.add(event_id)
        steps = event.get("source_steps")
        if not isinstance(steps, list) or not steps or not all(isinstance(x, int) for x in steps):
            add("invalid_steps", f"{base}.source_steps", "Must be a non-empty integer list")
            steps = []
        else:
            if steps != sorted(set(steps)):
                add("invalid_steps", f"{base}.source_steps", "Steps must be sorted and unique")
            for step in steps:
                if step not in source_by_step:
                    add("unknown_step", f"{base}.source_steps", f"Step {step} does not exist")
        if event.get("primary_category") not in CATEGORIES:
            add("invalid_enum", f"{base}.primary_category", "Expected D1-D8")
        secondary_category = event.get("secondary_category")
        if secondary_category is not None and secondary_category not in CATEGORIES:
            add("invalid_enum", f"{base}.secondary_category", "Expected D1-D8 or null")
        if event.get("primary_reason") not in REASONS:
            add("invalid_enum", f"{base}.primary_reason", "Expected R0-R8")
        secondary_reasons = event.get("secondary_reasons")
        if not isinstance(secondary_reasons, list) or any(r not in REASONS - {"R0"} for r in secondary_reasons):
            add("invalid_enum", f"{base}.secondary_reasons", "Expected a list containing R1-R8")
        elif len(secondary_reasons) != len(set(secondary_reasons)):
            add("duplicate_reason", f"{base}.secondary_reasons", "Secondary reasons must be unique")
        if event.get("decision_visibility") not in DECISION_VISIBILITY:
            add("invalid_enum", f"{base}.decision_visibility", "Invalid visibility")
        reason_visibility = event.get("reason_visibility")
        if reason_visibility not in REASON_VISIBILITY:
            add("invalid_enum", f"{base}.reason_visibility", "Invalid visibility")
        if event.get("confidence") not in CONFIDENCE:
            add("invalid_enum", f"{base}.confidence", "Invalid confidence")
        if reason_visibility == "UNAVAILABLE":
            if event.get("primary_reason") != "R0":
                add("unsupported_reason", f"{base}.primary_reason", "UNAVAILABLE requires R0")
            if event.get("reason_summary"):
                add("unsupported_reason", f"{base}.reason_summary", "UNAVAILABLE requires an empty summary")
            if secondary_reasons:
                add("unsupported_reason", f"{base}.secondary_reasons", "UNAVAILABLE requires no secondary reasons")
        elif event.get("primary_reason") == "R0":
            add("reason_visibility_conflict", f"{base}.primary_reason", "R0 requires UNAVAILABLE")
        for key in ("decision_summary", "selected_option"):
            if not isinstance(event.get(key), str) or not event.get(key, "").strip():
                add("empty_text", f"{base}.{key}", "Must be non-empty text")
        if not isinstance(event.get("reason_summary"), str):
            add("type_error", f"{base}.reason_summary", "Must be text")
        if event.get("alternative_visible") is not None and not isinstance(event.get("alternative_visible"), str):
            add("type_error", f"{base}.alternative_visible", "Must be text or null")

        evidence = event.get("evidence")
        if not isinstance(evidence, list) or not evidence:
            add("invalid_evidence", f"{base}.evidence", "At least one evidence item is required")
            continue
        for j, item in enumerate(evidence):
            item_path = f"{base}.evidence[{j}]"
            if not isinstance(item, dict):
                add("invalid_evidence", item_path, "Evidence must be an object")
                continue
            if set(item) != {"step", "field", "excerpt"}:
                add("invalid_evidence", item_path, "Expected exactly step, field, excerpt")
                continue
            step_id = item.get("step")
            field = item.get("field")
            excerpt = item.get("excerpt")
            if step_id not in source_by_step:
                add("unknown_step", f"{item_path}.step", "Evidence step does not exist")
                continue
            if steps and step_id not in steps:
                add("evidence_outside_event", f"{item_path}.step", "Evidence step is outside source_steps")
            if field not in EVIDENCE_FIELDS:
                add("invalid_enum", f"{item_path}.field", "Invalid evidence field")
                continue
            source_text = source_by_step[step_id].get(field)
            if not isinstance(excerpt, str) or not excerpt:
                add("invalid_evidence", f"{item_path}.excerpt", "Excerpt must be non-empty")
            elif len(excerpt) > 1000:
                add("invalid_evidence", f"{item_path}.excerpt", "Excerpt exceeds 1000 characters")
            elif not isinstance(source_text, str) or excerpt not in source_text:
                add("unsupported_evidence", f"{item_path}.excerpt", "Excerpt is not an exact source substring")
    return errors
