from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any, Protocol

from .core import read_jsonl


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
