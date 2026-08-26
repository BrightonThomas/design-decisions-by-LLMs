"""Interactive CLI viewer for close reading of normalized or curated trajectories.

Use it to read a trajectory from start to finish and inspect potential
design-decision points.

Usage:
    python -m zest.viewer data/curated/terminal_bench_2_1/trajectories.jsonl --list
    python -m zest.viewer data/curated/terminal_bench_2_0/trajectories.jsonl --index 0

Keys at the prompt:  t = next trajectory, q = quit.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from rich.console import Console

from .schema import Trajectory, read_jsonl

OBS_PREVIEW_CHARS = 2_000


def show_trajectory(console: Console, t: Trajectory) -> None:
    console.rule(f"[bold]{t.source} | {t.agent} | {t.model or 'unknown model'}[/bold]")
    console.print(f"task: {t.task_id}   steps: {len(t.steps)}   resolved: {t.resolved}\n")

    if not t.steps:
        console.print("[dim](no steps recorded)[/dim]")
        return

    for i, step in enumerate(t.steps):
        console.rule(f"step {i + 1}/{len(t.steps)}", style="dim")
        parts = [p for p in (step.thought, step.action) if p]
        if step.observation:
            obs = step.observation
            if len(obs) > OBS_PREVIEW_CHARS:
                obs = obs[:OBS_PREVIEW_CHARS] + f"\n... [{len(obs) - OBS_PREVIEW_CHARS} more chars]"
            parts.append(obs)
        console.print("\n\n".join(parts) if parts else "[dim](no content)[/dim]")


def view(trajectories: list[Trajectory], start: int) -> None:
    console = Console()
    ti = start
    while True:
        show_trajectory(console, trajectories[ti])
        cmd = input("\n[t]raj next  [q]uit > ").strip().lower()
        if cmd == "q":
            return
        ti = (ti + 1) % len(trajectories)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("file", type=Path, help="a normalized or curated trajectory .jsonl file")
    ap.add_argument("--list", action="store_true", help="list trajectories instead of viewing")
    ap.add_argument("--index", type=int, default=0, help="trajectory index to start at")
    args = ap.parse_args()

    trajectories = list(read_jsonl(args.file))
    if not trajectories:
        raise SystemExit(f"No trajectories in {args.file}")

    if args.list:
        for i, t in enumerate(trajectories):
            print(f"[{i:3}] {t.source} | {t.agent} | {t.task_id} | "
                  f"{len(t.steps)} steps | resolved={t.resolved}")
        return
    view(trajectories, min(args.index, len(trajectories) - 1))


if __name__ == "__main__":
    main()
