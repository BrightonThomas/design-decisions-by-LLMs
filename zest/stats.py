"""Corpus statistics over the analysis-ready trajectories.

Reports, per (source, agent): distinct model count, trajectory count,
resolution rate, step counts, and what share of steps carry any reasoning
text ("thought") — the week-1 data-availability check for the thesis.
(Average thought *length* was dropped as a metric: the field can hold raw
code/bash as easily as prose, so character count doesn't mean "more
reasoning".) Also reports task overlap (same task solved by multiple
agents), which is what makes the matched-task consistency comparison (RQ3)
possible.

Usage:
    python -m zest.stats
"""

from __future__ import annotations

from collections import defaultdict
from statistics import mean

from rich.console import Console
from rich.table import Table

from .paths import CURATED_TERMINAL_BENCH, NORMALIZED_DIR
from .schema import read_jsonl


def main() -> None:
    console = Console()
    # Terminal-Bench analyses use the curated outcome-enriched corpora.
    # SWE-bench and MOSAIC have no curated layer and remain normalized inputs.
    files = [
        path
        for path in (
            NORMALIZED_DIR / "swebench.jsonl",
            NORMALIZED_DIR / "mosaic.jsonl",
            *CURATED_TERMINAL_BENCH.values(),
        )
        if path.exists()
    ]
    if not files:
        console.print("No analysis-ready data found. Run the parsers and Terminal-Bench curation first.")
        return

    groups: dict[tuple[str, str], list] = defaultdict(list)
    task_agents: dict[tuple[str, str], set[str]] = defaultdict(set)
    for f in files:
        for t in read_jsonl(f):
            groups[(t.source, t.agent)].append(t)
            task_agents[(t.source, t.task_id)].add(t.agent)

    table = Table(title="ZEST demo corpus")
    for col in ("source", "agent", "models", "trajs", "resolved", "avg steps",
                "steps w/ thought", "avg duration"):
        table.add_column(col, justify="right" if col != "agent" else "left")

    for (source, agent), ts in sorted(groups.items()):
        all_steps = [s for t in ts for s in t.steps]
        thoughts = [s.thought for s in all_steps if s.thought]
        known = [t.resolved for t in ts if t.resolved is not None]
        models = {t.model for t in ts if t.model}
        durations = [t.duration_seconds for t in ts if t.duration_seconds is not None]
        table.add_row(
            source,
            agent,
            str(len(models)),
            str(len(ts)),
            f"{sum(known)}/{len(known)}" if known else "?",
            f"{mean(len(t.steps) for t in ts):.1f}",
            f"{100 * len(thoughts) / len(all_steps):.1f}%" if all_steps else "-",
            f"{mean(durations) / 60:.1f}min" if durations else "-",
        )
    console.print(table)

    overlaps = {k: v for k, v in task_agents.items() if len(v) > 1}
    console.print(
        f"\nMatched tasks (same task, >1 agent): [bold]{len(overlaps)}[/bold]"
    )
    for (source, task_id), agents in list(overlaps.items())[:10]:
        console.print(f"  {source}:{task_id} <- {', '.join(sorted(agents))}")
    if not overlaps:
        console.print(
            "  (expected at demo scale with one submission — overlap appears once "
            "multiple submissions covering the same split are fetched)"
        )


if __name__ == "__main__":
    main()
