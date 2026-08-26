# Design Decisions by LLMs — trajectory analysis pipeline

Pipeline prototype for the thesis **"Design Decisions in LLM Agent Reasoning"**.

Goal of this demo: prove the design end-to-end — fetch agent trajectories
from public sources, normalize them into one schema, check how much
reasoning text they actually contain, and read them step by step.

**Terminal-Bench 2.0 and 2.1 are the core analysis sources** — full-corpus
data (`--all`), used for Month 1's actual findings (the bi-weekly deck).
SWE-bench and MOSAIC stay demo-scale samples (tens/hundreds of records, not
full corpora) and are deliberately excluded from aggregate analysis for
now — mixing demo-scale samples into corpus-wide numbers skews them. They
remain a named future addition (see Month 2 below) once fetched at a
comparable scale.

## Pipeline

```
fetchers -> data/raw -> parse -> data/normalized
                                  |
                                  +-> curate_terminalbench -> data/curated/terminal_bench_2_*/trajectories.jsonl
                                                                  |
                                                                  +-> stats / notebooks / viewer
```

Unified schema (`zest/schema.py`): one `Trajectory` per task attempt
(source, agent, model, task_id, resolved, duration_seconds) holding an
ordered list of `Step`s — the unit of analysis for the thesis. Each step
captures the agent's reasoning, the action taken, and the action's result,
plus a timestamp where the source provides one. `duration_seconds` is the
trajectory's wall-clock span, mined from those per-step timestamps
(currently Terminal-Bench 2.0/2.1 only — see `zest/parse.py`'s
`atif_trajectory()`).

## Month 3 decision extraction

The task-specific Week 2 extractor prototype is in
`zest/decision_extractor/`. It uses `annotations/codebook_v1.md`, the strict
`annotations/decision_event_schema_v1.json`, and the versioned prompt to
produce and evaluate observable decision events. See
`zest/decision_extractor/README.md` for the fixed pilot, commands, validation
metrics, and the distinction between gold-replay plumbing tests and genuine
LLM accuracy.

## Setup

```
cd design-decisions-by-LLMs
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

Optional but recommended: set `GITHUB_TOKEN` (any free personal access token)
to avoid GitHub's 60 requests/hour anonymous rate limit:

```
set GITHUB_TOKEN=ghp_yourtoken
```

## Run (in order)

### 1. SWE-bench trajectories (core source — live reasoning)

```
python -m zest.fetch_swebench --list --split lite
python -m zest.fetch_swebench --submission 20240402_sweagent_gpt4 --split lite
```

Downloads **10** trajectories (change with `--limit`) from one leaderboard
submission into `data/raw/swebench/`, plus `results.json` for pass/fail
outcomes. If a submission stores its trajectories on S3 instead of in the
repo, the script says so — just pick another submission from `--list`
(older 2024 submissions are reliably in-repo).

### 2. Terminal-Bench 2.0 trajectories (MAIN reasoning source — auto download)

Terminal-Bench 2.0 reasoning trajectories come from the **tbench.ai
leaderboard** (the HuggingFace mirror only stores stdout/results, not the
agent's trajectory — confirmed dead end). Each run page's "Download Results"
archive contains its full ATIF-v1.6 trajectory; the fetcher calls the same
download API the site's button uses and keeps just the trajectory JSON:

```
python -m zest.fetch_tbench20 --limit 10
```

This walks leaderboard → agent/model → task → trial, extracting one trajectory
per run into `data/raw/tbench2.0/<uuid>-traj.json`. Options:
- `--per-agent N` — how many runs to take per agent/model (default 1, for
  cross-scaffold variety; raise it to sample one scaffold more deeply).
- `--all` — download every run of every task for every agent/model (the full
  corpus; long-running, resumable — already-downloaded files are skipped).
- `--url <run-or-submission-URL>` (repeatable) / `--urls-file f.txt` — download
  specific runs instead of auto-walking.
- `--list-local` — list what's already downloaded.

Important: **many leaderboard runs don't publish a results archive** (most
are skipped automatically). If a run fails server-side (500) it's skipped
too. So a `--limit 10` run may fetch many pages; re-run to continue if it
comes up short.

The files are JSON in the **ATIF-v1.6** schema; `zest.parse` normalizes them
via `atif_trajectory()`:
- agent tool calls → one step each: `thought` = the tool call's `description`,
  `action` = `function_name` + command, `observation` = the step's result.
- plain agent messages → a thought-only step.
- the system prompt and task prompt are stored in `Trajectory.meta`
  (`system_prompt`, `task_prompt`), not as decision steps.

ATIF itself carries no pass/fail field, but `resolved` is captured anyway:
`zest/tbench20_web.py` scrapes each trial's pass/fail outcome as a free side
effect of the normal fetch (it's embedded in the same task page's Next.js
flight data already being read for the trial-uuid list — no extra request),
and `zest/parse.py`'s `parse_tbench()` applies it via a `_rewards.json`
uuid→reward map.

### 3. Terminal-Bench 2.1 trajectories (Harbor hub — auto download)

2.1 moved off tbench.ai's embedded pages to the **Harbor hub + GitHub**:
entries live in `harbor-framework/terminal-bench-2-1`'s
`leaderboard/submissions/*.json`, and each trial's ATIF-v1.7 trajectory is
served from the hub's trajectory API.

```
python -m zest.fetch_tbench21 --list
python -m zest.fetch_tbench21 --limit-per-entry 5 --max-entries 2
python -m zest.fetch_tbench21 --all
```

Files land in `data/raw/tbench2.1/<agent>__<model>/<trialId>-traj.json`.
`--all` pulls the full corpus (~6000+ trajectories; long-running, resumable).
`--rewards` is meant to build a `_rewards.json` trial→pass/fail map the same
way 2.0's is captured, but **it's currently non-functional** — see Known
limitations below.

### 4. MOSAIC sample (real-world agent PRs — breadth, not live reasoning)

```
python -m zest.fetch_mosaic
```

**Streams** the first 200 rows (`--limit`) — never downloads the full ~110k-PR
dataset. If the default config/split fails, the script prints the available
ones; retry with `--config`/`--split`.

### 5. Normalize everything into one schema

```
python -m zest.parse --source all
```

Writes `data/normalized/<source>.jsonl` and reports what was parsed vs.
skipped per source. Individual sources: `--source swebench|tbench|tbench21|mosaic`.

### 6. Corpus stats (the data-availability check)

First build the analysis-ready Terminal-Bench files:

```
python -m zest.curate_terminalbench
```

This preserves `data/normalized` as the source layer and writes the final
analysis inputs under `data/curated/terminal_bench_2_0` and
`data/curated/terminal_bench_2_1`. Terminal-Bench 2.0 contains only usable
trajectories with known outcomes; 2.1 retains every usable local trajectory
and marks missing outcomes with `resolved_available: false`.

```
python -m zest.stats
```

Per source/agent: distinct model count, trajectory count, resolution rate,
avg. steps per trajectory, **% of steps carrying any reasoning text**
(a presence check — the field can hold code/bash as easily as prose, so
length isn't tracked as a metric), **avg. duration** (mined from ATIF
per-step timestamps, in minutes), and matched tasks solved by more than one
agent (basis for the RQ3 consistency comparison).

### 7. Content-type classification

```
python -m zest.content_types
```

Classifies every piece of step text in the curated Terminal-Bench 2.0/2.1
datasets as
natural language, bash, a tool call, or non-determinable, and reports one
combined breakdown per (source, agent): step count plus the four category
percentages. Bash/tool-call detection is exact syntax checking (shell
operators, JSON validity); natural-language detection uses `py3langid`, a
trained language-ID model, not a keyword heuristic. One caveat baked into
the numbers, documented in full in the module's own docstring: four
harnesses (terminus-2, terminus-3-3, terminus-kira-env-bootstrap, judy)
show near-100% "tool call" because their real bash text sits under an ATIF
argument key `zest/parse.py` doesn't read yet — a known parsing gap, not
real agent behavior.

### 8. Close reading

```
python -m zest.viewer data/normalized/swebench.jsonl --list
python -m zest.viewer data/curated/terminal_bench_2_0/trajectories.jsonl --index 0
```

Prints one whole trajectory at a time, straight through — a header (source,
agent, model, task, resolved) followed by every step's content in order,
divided by a light rule between steps. Keys: `t` = next trajectory,
`q` = quit. This is the workflow Month 2's manual annotation builds on.

## Data sources

| Source | What | Where | Status |
|---|---|---|---|
| Terminal-Bench 2.0 | ATIF-v1.6 reasoning trajectories (auto download) | tbench.ai/leaderboard/terminal-bench/2.0 | Core — full corpus |
| Terminal-Bench 2.1 | ATIF-v1.7 reasoning trajectories (auto download) | hub.harborframework.com + github.com/harbor-framework/terminal-bench-2-1 | Core — full corpus |
| SWE-bench submissions | leaderboard reasoning traces (`trajs/`) | github.com/swe-bench/experiments | Demo-scale, excluded from core analysis |
| MOSAIC | ~110k real-world agent PRs (Codex, Claude Code, Copilot, Jules, Devin) | HF: AISE-TUDelft/MOSAIC-agentic-3m | Demo-scale, excluded from core analysis |

## Known limitations

- One SWE-bench submission at a time; matched-task overlap only appears once
  several submissions of the same split are fetched.
- SWE-bench/MOSAIC field mappings are best-effort until the real file
  layouts are inspected; unknown formats are logged and skipped.
- MOSAIC PRs become single-step trajectories (decision-in-practice records) —
  they complement, not replace, the step-level reasoning sources.
- Terminal-Bench 2.0 has complete pass/fail coverage in the curated dataset.
  Terminal-Bench 2.1 outcomes are filled from the downloaded longitudinal
  metadata where available; rows without matching outcome metadata remain in
  the curated dataset with `resolved_available: false`.
- SWE-bench and MOSAIC are demo-scale samples, deliberately excluded from
  core/aggregate analysis (see the top of this README).

## Month 2 — annotation tooling

Month 1 built and validated the pipeline end-to-end (fetch → normalize →
stats → content-type classification → close reading) and produced the
bi-weekly findings deck. Month 2's headline goal:

- **Annotation tooling**: extend `zest.viewer` so design-decision points can
  be marked directly on real trajectories while reading them — the manual
  annotation workflow the whole pipeline has been building toward.

Other open items carried forward:
- Investigate the 1,237 Terminal-Bench 2.1 trajectories without matching
  outcome metadata; keep them flagged rather than deleting them.
- Bring SWE-bench/MOSAIC into the core analysis once fetched at a
  comparable scale to Terminal-Bench (currently 10 and 200 records vs.
  tens of thousands).
- Dedicated parsers for the SWE-bench/MOSAIC formats `zest.parse` currently
  logs as "skipped".
- Fetch 2–3 SWE-bench submissions on the same split to get matched tasks
  (SWE-bench's own matched-task overlap, independent of Terminal-Bench's).
