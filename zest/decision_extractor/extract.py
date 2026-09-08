from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import EXTRACTOR_VERSION, PROMPT_VERSION, SCHEMA_VERSION
from .core import parse_response, read_jsonl, select_trajectories, validate_extraction, write_jsonl
from .prompting import render_prompt
from .providers import CodexCliProvider, CommandProvider, FixtureProvider


def run_extraction(
    trajectories: list[dict[str, Any]],
    template_path: Path,
    schema_path: Path,
    provider: Any,
    model_name: str | None = None,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for index, trajectory in enumerate(trajectories, 1):
        print(
            f"[{index}/{len(trajectories)}] extracting {trajectory['task_id']} "
            f"({trajectory['trial_id']})",
            flush=True,
        )
        prompt = render_prompt(template_path, schema_path, trajectory)
        record: dict[str, Any] = {
            "extractor_version": EXTRACTOR_VERSION,
            "prompt_version": PROMPT_VERSION,
            "schema_version": SCHEMA_VERSION,
            "provider": provider.name,
            "extractor_model": model_name,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "task_id": trajectory["task_id"],
            "trial_id": trajectory["trial_id"],
            "source_model": trajectory.get("model"),
            "source_harness": trajectory.get("harness"),
            "valid": False,
            "errors": [],
            "extraction": None,
        }
        try:
            extraction = parse_response(provider.complete(prompt, trajectory))
            errors = validate_extraction(extraction, trajectory)
            record["extraction"] = extraction
            record["errors"] = errors
            record["valid"] = not errors
        except Exception as exc:  # preserve failures for error-rate analysis
            record["errors"] = [{
                "code": "provider_or_parse_error",
                "path": "",
                "message": f"{type(exc).__name__}: {exc}",
            }]
        records.append(record)
    return records


def prepare_outbox(
    trajectories: list[dict[str, Any]], template_path: Path, schema_path: Path
) -> list[dict[str, Any]]:
    return [{
        "prompt_version": PROMPT_VERSION,
        "schema_version": SCHEMA_VERSION,
        "task_id": trajectory["task_id"],
        "trial_id": trajectory["trial_id"],
        "source_model": trajectory.get("model"),
        "source_harness": trajectory.get("harness"),
        "prompt": render_prompt(template_path, schema_path, trajectory),
    } for trajectory in trajectories]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Extract observable design decisions")
    parser.add_argument("--input", type=Path, required=True, help="Trajectory JSONL")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--schema", type=Path, required=True)
    parser.add_argument("--prompt", type=Path, required=True)
    parser.add_argument("--provider", choices=("outbox", "fixture", "command", "codex"), required=True)
    parser.add_argument("--fixture", type=Path)
    parser.add_argument("--command-json", help='Example: ["claude","-p"]')
    parser.add_argument("--codex-executable", default="codex")
    parser.add_argument("--model-name")
    parser.add_argument("--task-id")
    parser.add_argument("--trial-id", action="append", default=[])
    parser.add_argument("--resolved-only", action="store_true")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--timeout", type=int, default=600)
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Keep valid output records and process only missing or invalid trials",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    trajectories = select_trajectories(
        args.input,
        task_id=args.task_id,
        trial_ids=set(args.trial_id) or None,
        resolved_only=args.resolved_only,
        limit=args.limit,
    )
    if not trajectories:
        raise SystemExit("No matching trajectories")
    if args.provider == "outbox":
        count = write_jsonl(prepare_outbox(trajectories, args.prompt, args.schema), args.output)
        print(json.dumps({"mode": "outbox", "records": count, "output": str(args.output)}))
        return
    if args.provider == "fixture":
        if not args.fixture:
            raise SystemExit("--fixture is required with --provider fixture")
        provider = FixtureProvider(args.fixture)
    elif args.provider == "codex":
        provider = CodexCliProvider(
            schema_path=args.schema,
            model_name=args.model_name,
            executable=args.codex_executable,
            timeout_seconds=args.timeout,
        )
    else:
        if not args.command_json:
            raise SystemExit("--command-json is required with --provider command")
        provider = CommandProvider(args.command_json, args.timeout)
    recorded_model = args.model_name
    if args.provider == "codex" and not recorded_model:
        recorded_model = "codex-cli-default"
    existing: list[dict[str, Any]] = []
    if args.resume and args.output.exists():
        existing = list(read_jsonl(args.output))
    valid_existing = {
        str(record.get("trial_id")): record
        for record in existing
        if record.get("valid") is True
    }
    pending = [
        trajectory for trajectory in trajectories
        if trajectory["trial_id"] not in valid_existing
    ]
    new_records = run_extraction(pending, args.prompt, args.schema, provider, recorded_model)
    new_by_trial = {str(record["trial_id"]): record for record in new_records}
    records = [
        new_by_trial.get(trajectory["trial_id"])
        or valid_existing[trajectory["trial_id"]]
        for trajectory in trajectories
        if trajectory["trial_id"] in new_by_trial or trajectory["trial_id"] in valid_existing
    ]
    count = write_jsonl(records, args.output)
    print(json.dumps({
        "mode": provider.name,
        "records": count,
        "valid": sum(bool(r["valid"]) for r in records),
        "reused": len(valid_existing),
        "processed": len(new_records),
        "output": str(args.output),
    }))


if __name__ == "__main__":
    main()
