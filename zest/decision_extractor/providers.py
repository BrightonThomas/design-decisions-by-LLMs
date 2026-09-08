from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Protocol

from .core import read_jsonl


UNSUPPORTED_STRUCTURED_OUTPUT_KEYWORDS = {
    "$schema", "$id", "title", "description", "default", "examples",
    "uniqueItems", "minItems", "maxItems", "minimum", "maximum",
    "exclusiveMinimum", "exclusiveMaximum", "minLength", "maxLength",
    "pattern", "format",
}


def codex_output_schema(value: Any) -> Any:
    """Reduce JSON Schema to the subset accepted by Codex structured output."""
    if isinstance(value, list):
        return [codex_output_schema(item) for item in value]
    if not isinstance(value, dict):
        return value
    cleaned: dict[str, Any] = {}
    for key, item in value.items():
        if key in UNSUPPORTED_STRUCTURED_OUTPUT_KEYWORDS:
            continue
        cleaned["anyOf" if key == "oneOf" else key] = codex_output_schema(item)
    if "type" not in cleaned:
        candidates = cleaned.get("enum")
        if "const" in cleaned:
            candidates = [cleaned["const"]]
        if isinstance(candidates, list) and candidates:
            if all(isinstance(item, str) for item in candidates):
                cleaned["type"] = "string"
            elif all(isinstance(item, int) and not isinstance(item, bool) for item in candidates):
                cleaned["type"] = "integer"
    return cleaned


class Provider(Protocol):
    name: str

    def complete(self, prompt: str, trajectory: dict[str, Any]) -> str: ...


class FixtureProvider:
    """Deterministic responses for plumbing tests; never an accuracy estimate."""

    name = "fixture"

    def __init__(self, fixture_path: Path):
        self.responses: dict[str, Any] = {}
        for record in read_jsonl(fixture_path):
            trial_id = str(record["trial_id"])
            self.responses[trial_id] = record.get("response", record.get("extraction"))

    def complete(self, prompt: str, trajectory: dict[str, Any]) -> str:
        response = self.responses.get(trajectory["trial_id"])
        if response is None:
            raise KeyError(f"No fixture response for trial {trajectory['trial_id']}")
        return response if isinstance(response, str) else json.dumps(response, ensure_ascii=False)


class CommandProvider:
    """Run an explicitly supplied LLM command; prompt is sent on stdin."""

    name = "command"

    def __init__(self, command_json: str, timeout_seconds: int = 600):
        command = json.loads(command_json)
        if not isinstance(command, list) or not command or not all(isinstance(x, str) for x in command):
            raise ValueError("--command-json must be a JSON array of command arguments")
        self.command = command
        self.timeout_seconds = timeout_seconds

    def complete(self, prompt: str, trajectory: dict[str, Any]) -> str:
        result = subprocess.run(
            self.command,
            input=prompt,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            timeout=self.timeout_seconds,
            check=False,
            shell=False,
        )
        if result.returncode != 0:
            message = result.stderr.strip() or f"exit code {result.returncode}"
            raise RuntimeError(f"Provider command failed: {message}")
        return result.stdout


class CodexCliProvider:
    """Use the authenticated local Codex CLI as a replaceable extractor backend."""

    name = "codex-cli"

    def __init__(
        self,
        schema_path: Path,
        model_name: str | None = None,
        executable: str = "codex",
        timeout_seconds: int = 900,
    ):
        self.schema_path = schema_path.resolve()
        self.model_name = model_name
        self.executable = executable
        self.timeout_seconds = timeout_seconds

    def complete(self, prompt: str, trajectory: dict[str, Any]) -> str:
        # An empty temporary working directory prevents the annotation model from
        # consulting repository files instead of the supplied trajectory.
        with tempfile.TemporaryDirectory(prefix="decision-extractor-") as work_dir:
            output_path = Path(work_dir) / "response.json"
            cli_schema_path = Path(work_dir) / "output-schema.json"
            source_schema = json.loads(self.schema_path.read_text(encoding="utf-8"))
            cli_schema_path.write_text(
                json.dumps(codex_output_schema(source_schema), ensure_ascii=False),
                encoding="utf-8",
            )
            command = [
                self.executable,
                "exec",
                "--ephemeral",
                "--ignore-user-config",
                "--skip-git-repo-check",
                "--sandbox",
                "read-only",
                "--cd",
                work_dir,
                "--output-schema",
                str(cli_schema_path),
                "--output-last-message",
                str(output_path),
            ]
            if self.model_name:
                command.extend(["--model", self.model_name])
            command.append("-")
            environment = os.environ.copy()
            if not environment.get("CODEX_HOME") and environment.get("USERPROFILE"):
                environment["CODEX_HOME"] = str(Path(environment["USERPROFILE"]) / ".codex")
            result = subprocess.run(
                command,
                input=prompt,
                text=True,
                encoding="utf-8",
                errors="replace",
                capture_output=True,
                timeout=self.timeout_seconds,
                check=False,
                shell=False,
                env=environment,
            )
            if result.returncode != 0:
                message = result.stderr.strip() or result.stdout.strip() or f"exit code {result.returncode}"
                if len(message) > 4000:
                    message = "...[provider output truncated]...\n" + message[-4000:]
                raise RuntimeError(f"Codex CLI failed: {message}")
            if not output_path.exists():
                raise RuntimeError("Codex CLI did not write its final response")
            return output_path.read_text(encoding="utf-8")
