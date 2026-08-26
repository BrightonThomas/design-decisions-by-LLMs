"""Unified trajectory schema.

TerminalBench 2.0 and 2.1 runs are normalized into the same two structures
so that all downstream analysis
(stats, viewing, annotation, extraction) works on one format:

    Trajectory
      source            "tbench" | "tbench21"
      agent             scaffold name (e.g. "sweagent", "claude-code")
      model             underlying LLM if known
      task_id           benchmark task identifier
      resolved          True/False if outcome is known, else None
      steps             ordered list of Step
      duration_seconds  wall-clock span of the run (last step timestamp minus
                         first), if the source provides per-step timestamps;
                         else None -- currently only tbench/tbench21 (ATIF)
      meta              source-specific extras (kept small)

    Step
      index        position in the trajectory
      thought      the agent's reasoning text at this step (may be None)
      action       the action taken (command, tool call, edit)
      observation  what the environment returned
      timestamp    ISO-8601 timestamp of this step, if the source provides
                    one (ATIF sources only); else None

Serialized as JSONL: one Trajectory per line.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Iterable, Iterator, Optional

from .paths import replace_with_retry


@dataclass
class Step:
    index: int
    thought: Optional[str] = None
    action: Optional[str] = None
    observation: Optional[str] = None
    timestamp: Optional[str] = None


@dataclass
class Trajectory:
    source: str
    agent: str
    model: Optional[str]
    task_id: str
    resolved: Optional[bool] = None
    steps: list[Step] = field(default_factory=list)
    duration_seconds: Optional[float] = None
    meta: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Trajectory":
        steps = [Step(**s) for s in d.get("steps", [])]
        return cls(
            source=d["source"],
            agent=d["agent"],
            model=d.get("model"),
            task_id=d["task_id"],
            resolved=d.get("resolved"),
            steps=steps,
            duration_seconds=d.get("duration_seconds"),
            meta=d.get("meta", {}),
        )


def write_jsonl(trajectories: Iterable[Trajectory], path: Path) -> int:
    """Write trajectories as JSONL. Returns the number written.

    Writes to a temp file and atomically renames it into place, so a reader
    (e.g. `zest.stats` run concurrently) never observes a partially-written
    file -- it sees either the old complete file or the new complete one,
    never a torn line mid-write."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    n = 0
    with open(tmp, "w", encoding="utf-8") as f:
        for t in trajectories:
            f.write(json.dumps(t.to_dict(), ensure_ascii=False, default=str) + "\n")
            n += 1
    replace_with_retry(tmp, path)
    return n


def read_jsonl(path: Path) -> Iterator[Trajectory]:
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                yield Trajectory.from_dict(json.loads(line))
