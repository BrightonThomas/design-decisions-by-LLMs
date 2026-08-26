"""Classify trajectory text as natural language, bash, a tool call, or
non-determinable -- a content-*shape* breakdown, distinct from the
thought-coverage percentage `zest.stats` already reports.

The classifier operates on the curated TerminalBench 2.0 and 2.1 corpora.

Hybrid classifier: `bash` and `tool_call` are exact syntax checks (shell
operators/verbs, JSON validity) -- a model has no edge over a parser/regex
for "does this contain &&" or "does this parse as JSON", so those stay
deterministic. `natural_language` uses py3langid, a real trained language-ID
model, instead of a hand-rolled stopword heuristic: real prose lands one
language clearly ahead of the field (empirically margin >~30 between the
top-2 guesses), while bash/JSON/bare-identifier text is nearly
indistinguishable across candidate languages (margin <~2) since there's no
linguistic signal for the model to key on -- see _LANGID_MARGIN_THRESHOLD.
Running an LLM over every snippet (millions, across tbench + tbench21)
isn't practical here; py3langid is fast enough (~3000 calls/sec) to cover
the full corpus in well under half an hour. Known weakness shared by all
language-ID approaches, not specific to this one: short phrases (under
~4-5 words) don't carry enough signal and fall through to
non_determinable -- treat the numbers as a heuristic signal, not ground
truth.

Known caveat baked into these numbers: `atif_trajectory()` (zest/parse.py)
reads a tool call's command from `arguments["command"]` or
`arguments["input"]`, but terminus-2 / terminus-3-3 /
terminus-kira-env-bootstrap store it under `arguments["keystrokes"]` instead,
and judy stores it under `arguments["cmd"]` -- neither key is read, so all
four harnesses' `action` field is currently just a bare tool name (e.g.
"bash_command") for essentially every step. That shows up here as those
harnesses' `action` column being almost entirely "tool call" -- an artifact
of the parsing gap, not a real property of what those agents do. Confirmed
every other harness (claude-code, cursor-cli, deepagent-harbor, codex,
gemini-cli) already uses the "command" key the parser expects, so they're
unaffected. Left as-is per instruction; not fixed by this module.

Usage:
    python -m zest.content_types
"""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict

import py3langid as langid
from rich.console import Console
from rich.table import Table

from .paths import CURATED_TERMINAL_BENCH
from .schema import read_jsonl

SOURCES = ("tbench", "tbench21")
FIELDS = ("thought", "action", "observation")
CATEGORIES = ("tool_call", "bash", "natural_language", "non_determinable")

_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_SHELL_OPERATORS = ("&&", "||", "|", ";", ">>", ">", "<", "`", "$(", "#!/bin/")
_SHELL_VERBS = {
    "ls", "cd", "cat", "echo", "grep", "find", "python", "python3", "pip", "pip3",
    "git", "mkdir", "rm", "cp", "mv", "curl", "wget", "sudo", "apt", "apt-get",
    "chmod", "chown", "export", "source", "bash", "sh", "awk", "sed", "tar",
    "docker", "npm", "npx", "node", "make", "kill", "ps", "top", "head", "tail",
    "wc", "sort", "uniq", "diff", "patch", "touch", "ln", "ssh", "systemctl",
    "service", "pwd", "printf", "vim", "nano", "tmux", "screen", "pytest", "go",
    "cargo", "javac", "java", "gcc", "g++", "which", "env", "yarn", "unzip",
    "zip", "ping", "nc", "netstat", "df", "du", "free", "uname", "whoami",
}
_CLI_FLAG_RE = re.compile(r"(?:^|\s)-{1,2}[A-Za-z][\w-]*")

# Margin between py3langid's top-2 language-guess scores. Empirically, real
# prose clears ~30; bash/JSON/bare-identifier text sits under ~2 (see
# module docstring). 5.0 leaves a wide safety margin between those two
# observed clusters while staying permissive enough for shorter real
# sentences that still carry some signal.
_LANGID_MARGIN_THRESHOLD = 5.0


def _looks_like_json(text: str) -> bool:
    t = text.strip()
    if not t or t[0] not in "{[":
        return False
    try:
        json.loads(t)
        return True
    except (json.JSONDecodeError, ValueError):
        return False


def classify_text(text: str | None) -> str | None:
    """One of "tool_call" | "bash" | "natural_language" | "non_determinable",
    or None if `text` is empty/whitespace-only (excluded from the
    denominator entirely -- same convention zest.stats uses for `thought`).
    Ordered heuristic, first match wins; see module docstring for why this
    isn't model-based."""
    if not text:
        return None
    t = text.strip()
    if not t:
        return None

    head, _, tail = t.partition(" ")
    tail = tail.strip()

    # 1. tool_call: a bare identifier (e.g. a tool name with no captured
    # arguments), raw JSON, or "<identifier> {json-tail}".
    if _IDENTIFIER_RE.match(t):
        return "tool_call"
    if _looks_like_json(t):
        return "tool_call"
    if _IDENTIFIER_RE.match(head) and tail[:1] in "{[" and _looks_like_json(tail):
        return "tool_call"

    # 2. bash: shell operators anywhere, or a leading/second-token shell verb,
    # or a CLI-flag pattern on a short-ish line.
    if any(op in t for op in _SHELL_OPERATORS):
        return "bash"
    first_word = re.split(r"[\s(]", t, maxsplit=1)[0].strip(",;:").lower()
    candidates = {first_word}
    if _IDENTIFIER_RE.match(head) and tail:
        candidates.add(tail.split(None, 1)[0].strip(",;:").lower())
    if candidates & _SHELL_VERBS:
        return "bash"
    if _CLI_FLAG_RE.search(t) and len(t.split()) <= 40:
        return "bash"

    # 3. natural_language: py3langid top-2 score margin (see module docstring
    # and _LANGID_MARGIN_THRESHOLD for why margin, not raw score).
    ranked = langid.rank(t)
    margin = float(ranked[0][1]) - float(ranked[1][1])
    if margin >= _LANGID_MARGIN_THRESHOLD:
        return "natural_language"

    # 4. fallback
    return "non_determinable"


def build_reports() -> dict[tuple[str, str], tuple[Counter, int]]:
    """(source, agent) -> (Counter over CATEGORIES, total step count).

    The Counter merges thought + action + observation into one combined
    tally per group -- the overall picture, not split out by field. It's
    classified-item counts, not step counts (a step can contribute 0-3
    items, one per field) -- percentages are computed against that same
    denominator. The step count is tracked separately and is what gets
    reported as `n`, since a raw classified-item count is confusing on its
    own (inflated by however many of the 3 fields happened to be non-empty)."""
    groups: dict[tuple[str, str], Counter] = defaultdict(Counter)
    n_steps: dict[tuple[str, str], int] = defaultdict(int)
    for src in SOURCES:
        path = CURATED_TERMINAL_BENCH[src]
        if not path.exists():
            continue
        for t in read_jsonl(path):
            key = (t.source, t.agent)
            for s in t.steps:
                n_steps[key] += 1
                for text in (s.thought, s.action, s.observation):
                    cat = classify_text(text)
                    if cat is not None:
                        groups[key][cat] += 1
    return {key: (groups[key], n_steps[key]) for key in n_steps}


def _print_table(console: Console, by_group: dict[tuple[str, str], tuple[Counter, int]]) -> None:
    table = Table(title="Content type -- overall (thought + action + observation)")
    for col in ("source", "agent", "n (steps)", "natural language", "bash", "tool call", "non-determinable"):
        table.add_column(col, justify="right" if col not in ("source", "agent") else "left")

    for (source, agent), (counts, n_steps) in sorted(by_group.items()):
        n_classified = sum(counts.values())
        if n_classified == 0:
            continue
        pct = {c: 100 * counts.get(c, 0) / n_classified for c in CATEGORIES}
        table.add_row(
            source,
            agent,
            str(n_steps),
            f"{pct['natural_language']:.0f}%",
            f"{pct['bash']:.0f}%",
            f"{pct['tool_call']:.0f}%",
            f"{pct['non_determinable']:.0f}%",
        )
    console.print(table)
    console.print()


def main() -> None:
    console = Console()
    if not any(CURATED_TERMINAL_BENCH[s].exists() for s in SOURCES):
        console.print("No curated Terminal-Bench data found. Run: python -m zest.curate_terminalbench")
        return

    groups = build_reports()
    _print_table(console, groups)

    console.print(
        "[dim]Caveat: terminus-2 / terminus-3-3 / terminus-kira-env-bootstrap store the real command "
        "under ATIF's \"keystrokes\" argument key, and judy under \"cmd\" -- neither is read by "
        "zest/parse.py, so their `action` field is almost entirely a bare tool name, hence the near-100% "
        "\"tool call\" share. That's a known parsing gap, not a real property of those agents' "
        "behavior.[/dim]"
    )


if __name__ == "__main__":
    main()
