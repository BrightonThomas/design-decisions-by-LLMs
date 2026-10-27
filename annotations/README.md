# Annotation resources

This directory contains the current annotation definitions and two compact
workbook examples. The examples are included to make the annotation approach
understandable without distributing the full TerminalBench datasets.

## Example workbooks

### `pypi-server-and-fix-git.xlsx`

Step-level annotations for two TerminalBench 2.1 tasks:

- `pypi-server`: build a small Python package and serve it from a local package
  index.
- `fix-git`: recover personal changes and merge them into the main branch.

The workbook preserves every recorded trajectory step. Original model, harness,
thought, action, and observation fields are visually separated from the
researcher-added annotations. Yellow cells highlight steps that are especially
useful for comparing implementation behavior.

### `llm-scheduler-single-trajectory.xlsx`

A detailed annotation of one resolved `llm-inference-batching-scheduler`
trajectory produced by Claude Fable 5 with the Claude Code harness. It contains:

- all 13 recorded trajectory steps;
- six linked decision events;
- decision and reason labels from Codebook V1; and
- the supporting source steps and evidence for each event.

The workbook has separate sheets for the trajectory, decision events, and a
compact codebook reference.

## Annotation specification

- `codebook_v2.md` defines the revised D1–D8 boundaries, decision-event rules,
  and the two decision visibility labels, Explicit and Contextual. It includes
  one example per category in a compact format for LLM input.
  It uses the step-level workbook's J–M fields.
- `archive/codebook_v2_before_boundary_revision_2026-10-13.md` preserves the
  previous broader V2 document, including its reason and confidence framework.
- `codebook_v1.md` provides a concise design-decision definition and the D1–D8
  taxonomy, with one illustrative example per category.
- `decision_event_schema_v1.json` defines the earlier machine-readable event
  format. Its reason, confidence, and visibility fields have not been updated
  to implement the revised V2 codebook.
- `extractor_prompt_v1.md` contains the earlier provider-independent extraction
  prompt and has not been updated for the revised V2 protocol.
- `open_coding_extractor_prompt_v2.md` contains the taxonomy-free pilot prompt,
  including atomic event-boundary rules and two synthetic examples.
- `extractor_version_log.md` records changes to the extraction protocol.

These files are working research artifacts. Labels may be revised after further
manual validation, but versioned changes should preserve the reasoning behind
each revision.
