# Design Decisions by LLMs
The project studies how an agent's underlying model and execution harness
influence its problem-solving process: which decisions appear, what evidence or
reasons accompany them, how visible the reasoning is, and how consistently the
same task is approached across repeated runs and model–harness combinations.

## Research scope

The analysis uses TerminalBench 2.0 and TerminalBench 2.1 trajectories. It is
organized around three questions:

1. What types of design decisions appear in recorded coding-agent trajectories?
2. How are those decisions and their reasons expressed in the available trace?
3. How consistent are decision–reason patterns across comparable tasks, models,
   harnesses, and repeated runs?

The repository supports both corpus-level measurement and close reading. The
current workflow combines deterministic data processing, manually reviewed
annotations, and a versioned prototype for LLM-assisted decision extraction.

## What is implemented

- TerminalBench 2.0 and 2.1 ingestion and ATIF trajectory parsing.
- A shared trajectory representation containing task, model, harness, outcome,
  duration, token metadata, and ordered steps.
- Separate raw, normalized, and analysis-ready data layers.
- Outcome enrichment and explicit availability flags when resolution metadata is
  missing.
- Corpus statistics covering task coverage, resolution, steps, completion time,
  token use, and model/harness groupings.
- Mean and median summaries for skewed effort measures.
- Same-harness/different-model and same-model/different-harness comparisons.
- Token-count auditing that compares reported usage with a tokenizer-based
  estimate over the recorded trajectory.
- Detailed task studies for `pypi-server`, `fix-git`, and
  `llm-inference-batching-scheduler`.
- Within-combination analysis for repeated resolved runs.
- Codebook V1, a strict event schema, an extractor prompt, source-evidence
  validation, and event-level evaluation.
- Small annotation examples that provide project context without including the
  full datasets.
- An on-demand OpenCode `/show_dx` command that analyzes a saved coding session
  with the D1–D8 codebook and produces a source-linked HTML review.

The [OpenCode integration guide](zest/opencode_dx/README.md) explains setup and
use. It snapshots a session only when the command is run; it does not capture
work live.

## Data flow

```text
TerminalBench trajectories
          |
          v
      data/raw
          |
          v
     zest.parse
          |
          v
   data/normalized
          |
          v
zest.curate_terminalbench
          |
          v
     data/curated
          |
          +--> corpus and token analyses
          +--> task-matched case studies
          +--> manual annotation
          +--> decision extraction and validation
```

The `thought`, `action`, and `observation` fields form a normalized analytical
view of each recorded step. Their availability and meaning depend on what the
original harness exposed; they should not be interpreted as uniformly complete
internal reasoning.

## Repository structure

```text
annotations/   Codebook, extraction contract, prompt, and curated examples
notebooks/     Corpus, token, task-level, and validation analyses
zest/          Data preparation, analysis, viewing, and extraction modules
data/          Local datasets; excluded from Git
outputs/       Generated tables and workbooks; excluded from Git
presentations/ Local slide decks; excluded from Git
```

The [annotation directory](annotations/README.md) contains two compact Excel
examples:

- `pypi-server-and-fix-git.xlsx` preserves every recorded step for two
  understandable software tasks and adds simple analyst labels.
- `llm-scheduler-single-trajectory.xlsx` links all steps of one resolved
  scheduler trajectory to six detailed decision events.


## Preparing TerminalBench data

Large datasets are deliberately excluded from version control. Place the raw
files under the expected local directories before running the pipeline:

```text
data/raw/tbench2.0/
data/raw/tbench2.1/
```

Normalize the raw trajectories:

```cmd
python -m zest.parse --source tbench
python -m zest.parse --source tbench21
```

Build the analysis-ready corpora and inspect summary statistics:

```cmd
python -m zest.curate_terminalbench
python -m zest.stats
python -m zest.content_types
```

TerminalBench 2.0 curation retains usable trajectories with known outcomes.
TerminalBench 2.1 retains usable trajectories and marks unavailable outcomes
explicitly instead of silently dropping them.

## Analysis notebooks

The notebooks cover complementary levels of analysis:

- `cross_corpus_analysis.ipynb`: TerminalBench 2.0/2.1 corpus statistics,
  model/harness groupings, effort metrics, and token summaries.
- `terminalbench21_token_count_audit.ipynb`: reported versus tokenizer-estimated
  token use across the full TerminalBench 2.1 corpus.
- `terminalbench21_understandable_task_selection.ipynb`: task-level comparisons
  designed for interpretable close reading.
- `two_task_resolved_trajectory_analysis.ipynb`: four-quadrant analysis of two
  resolved tasks.
- `terminalbench21_llm_inference_batching_scheduler_analysis.ipynb`: detailed
  analysis of the algorithm-heavy scheduler task, including repeated-run
  variation.
- The decision-extractor validation notebook provides a compact report for the
  extraction prototype.

Notebook outputs are retained where they help interpret the analysis, but the
large source datasets and generated exports remain local.

## Decision annotation and extraction

A decision event is a point where the agent commits to, revises, or stops a
course of action that meaningfully affects the subsequent solution process.
Routine reads, mechanical tool calls, and simple continuation are not decisions
unless they express such a choice.

The current annotation protocol records:

- source steps and supporting evidence;
- primary and optional secondary decision categories;
- selected option and visible alternative;
- primary and secondary reason codes;
- decision and reason visibility; and
- annotator confidence and review status.

The extractor implementation is under `zest/decision_extractor/`. It separates
prompt preparation, provider execution, response validation, and evaluation so
that model accuracy is not confused with pipeline correctness. A gold-replay
provider is included only as a plumbing test. A self-contained HTML viewer keeps
every candidate decision linked to its complete source steps for human review.

## Reproducibility and repository size

The Git repository contains code, notebooks, documentation, annotation
definitions, and small curated examples. It excludes:

- raw, normalized, and curated trajectory corpora;
- generated analysis outputs;
- virtual environments and dependency caches;
- local presentation files; and
- common large dataset, archive, and model-checkpoint formats.

This keeps the repository reviewable while preserving enough examples to
understand the research method.

## Interpretation limits

- Trace visibility is partly determined by the harness, so missing reasoning is
  not evidence that no reasoning occurred.
- Step counts are properties of the recorded trajectory format as well as the
  underlying solving process.
- Reported token fields and locally estimated tokens are related but not
  interchangeable measurements.
- Aggregate model/harness comparisons remain descriptive unless tasks and other
  relevant conditions are matched.
- Structural validation does not establish conceptual accuracy. Candidate
  events are spot-checked by a human before aggregate findings are reported.
