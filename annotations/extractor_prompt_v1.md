# Decision extractor prompt v1

You are annotating observable design decisions in a software-agent trajectory.
Use only the supplied task and trajectory. Do not infer private reasoning, use
model or harness identity as evidence, or reward verbosity.

## Decision test

Create an event only when all three conditions are supported:

1. the agent selects, rejects, prioritizes, or changes an option;
2. another plausible option existed;
3. the choice could affect approach, output, performance, correctness, validation, or completion.

Inspection, mechanical execution, routine reporting, and repeated commands are
not new decisions. Merge adjacent thought/action/observation steps that express
one choice. Merge an unchanged parameter sweep into one event. Do not duplicate
a decision when it is restated in a final summary.

## Decision categories

- D1: diagnostic or analytical strategy
- D2: algorithm or optimization strategy
- D3: shape or representation choice
- D4: parameter or configuration choice
- D5: implementation or computational-efficiency choice
- D6: recovery or strategy revision after a failure, constraint, or poor result
- D7: verification procedure choice
- D8: termination or submission choice

Tie-breaking: use D6 when a result directly triggers a meaningful revision; D2
for a changed algorithm; D3 for a changed representation/shape set; D4 when
only values or ranges change; D5 when the algorithm remains but its computation
changes; D7 for how success is checked; D8 for deciding to stop.

## Reason categories

- R0: no reason observable
- R1: task requirement or constraint
- R2: empirical data evidence
- R3: cost-model or mathematical evidence
- R4: performance or efficiency
- R5: correctness or validity
- R6: failure or unexpected result
- R7: simplicity or feasibility
- R8: environment, harness, or tool constraint

Reason visibility:

- EXPLICIT: recorded text states the choice and why.
- CONTEXTUAL: nearby action/observation supports the reason, but the agent does not state it.
- UNAVAILABLE: a choice is visible but no reason is supported. Use primary_reason R0,
  an empty reason_summary, and no secondary reasons.

Decision visibility:

- STATED: recorded thought or response states the selected option.
- BEHAVIOURAL: the option is visible only through action/artifact.
- AMBIGUOUS: the action may be a new choice or execution of an earlier choice.

## Evidence rules

- `source_steps` contains every and only the step IDs needed for the event.
- Each evidence excerpt must be an exact substring of the referenced field.
- Evidence can establish a visible action without establishing its reason.
- Missing thought text must never be replaced with an invented explanation.
- Use short excerpts (normally under 300 characters).

## Output rules

Return only one JSON object matching the supplied schema. No Markdown fences or
commentary. Keep events in chronological order and name them P01, P02, ... . An
empty event list is valid.

## Synthetic examples

Example A: thought says “The broad test is slow, so run only the failing parser
tests,” followed by the targeted test command. This is one D6 event, primary
reason R6, reason visibility EXPLICIT, and decision visibility STATED.

Example B: a step lists files and the next step reads a configuration file.
Neither is a decision unless the trajectory supports a meaningful choice of
inspection strategy.

Example C: an action tries five thresholds under one unchanged search policy and
then records the selected threshold. Treat the sweep and selection as one D4
event, not five events.

## JSON schema

{{SCHEMA_JSON}}

## Task and trajectory

{{TRAJECTORY_JSON}}
