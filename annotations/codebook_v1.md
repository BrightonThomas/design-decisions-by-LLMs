# Design-Decision Annotation Codebook v1

**Status:** Working calibration draft  
**Date:** 2026-08-23  
**Current calibration task:** `llm-inference-batching-scheduler`  
**Current source:** six resolved Terminal-Bench 2.1 trajectories  
**Source workbook:** `../outputs/llm_batching_annotations/llm_inference_batching_scheduler_trajectory_annotations.xlsx`

This draft is intentionally calibrated only on `llm-inference-batching-scheduler`. It must be reviewed and improved on this task before it is tested on other software tasks. It is not yet a frozen cross-task codebook.

## 1. Purpose

The codebook is used to identify observable design decisions in agent trajectories and record the evidence and reasons associated with those decisions. The resulting annotations will support comparisons between models and harnesses.

The codebook does **not** attempt to reconstruct hidden reasoning. It records only what is visible in the trajectory.

## 2. Source fields

Each trajectory step may contain:

- **Thought:** reasoning or planning text exposed in the recorded trajectory.
- **Action:** a tool call, command, file operation, response, or harness action.
- **Observation:** output returned by the environment or harness.

These fields are evidence with different meanings:

- Thought can explicitly state a choice or reason, but it should be treated as recorded text rather than direct access to a model's complete internal reasoning.
- Action can show which option was selected.
- Observation can show the evidence, failure, constraint, or result that triggered a later choice.
- A missing thought must never be replaced with an invented reason.

## 3. Unit of annotation

The main annotation unit is a **decision event**.

A decision event may occupy:

- one step;
- a thought step followed by an action step;
- an observation followed by a revision in later steps;
- several repeated search steps that implement one unchanged search policy.

Adjacent steps should be grouped when they belong to the same choice. Tool calls and trajectory steps are therefore not automatically separate decisions.

### 3.1 Decision-event definition

A decision event occurs when the agent observably selects, rejects, prioritizes, or changes a meaningful option that can affect the solution's design, performance, correctness, validation, or completion.

Examples include selecting:

- a batching or optimization algorithm;
- a request-grouping rule;
- a shared set of static shapes;
- a parameter or search range;
- a computational implementation of an algorithm;
- a recovery strategy after a failed result;
- a validation procedure;
- whether the solution is ready to submit.

### 3.2 Choice test

Annotate a candidate as a decision only when the available evidence supports all three questions:

1. **Selection:** Did the agent select, reject, prioritize, or change an option?
2. **Alternatives:** Could another plausible option have been used at that point?
3. **Consequence:** Could the selection materially affect the approach, output, performance, correctness, or completion?

If selection is visible but the existence of meaningful alternatives is unclear, label the candidate `UNCLEAR`. If the step simply executes a choice already made, label it `NOT_DECISION`.

### 3.3 Top-level label

Every reviewed step or step range receives one of these labels:

| Label | Meaning |
|---|---|
| `DECISION` | The choice test is satisfied. |
| `NOT_DECISION` | The step is inspection, execution, reporting, or a mechanical operation without a new meaningful choice. |
| `UNCLEAR` | The recorded data is insufficient to determine whether a meaningful choice occurred. |

## 4. Decision categories

Assign one **primary category** to each `DECISION`. A secondary category may be recorded during calibration, but it must not replace the primary label.

### D1 — Diagnostic or analytical strategy

The agent chooses an analysis, experiment, measurement, or comparison intended to distinguish between possible approaches.

Include:

- calculating lower bounds to determine feasibility;
- testing the sensitivity of cost to shape reuse;
- comparing grouping strategies to identify a bottleneck;
- choosing a targeted diagnostic after an unexpected result.

Exclude:

- routine file listing or reading;
- counting records without a visible analytical purpose;
- executing every exploratory command as a separate decision.

Task example: Claude Fable 5 computes singleton and per-shape lower bounds before choosing its optimizer design, steps 6–8.

### D2 — Algorithm or optimization strategy

The agent chooses the main mathematical or algorithmic method used to construct batches or optimize the plan.

Include:

- dynamic programming;
- greedy merging;
- grid-based clustering;
- grouping by aligned prompt length and generation length;
- changing from one optimization strategy to another.

Exclude:

- selecting only a numeric weight while keeping the algorithm unchanged;
- writing or running code after the strategy is already selected.

Task example: Claude Fable 5 chooses a per-sequence-level dynamic program and a lambda search, steps 9–10.

### D3 — Shape or representation choice

The agent chooses the shared static shapes or the representation used to map requests to shapes.

Include:

- selecting the global set of at most eight shapes;
- deciding how aligned prompt lengths map to shared shapes;
- changing a shape set because the two buckets cannot use independent sets.

Exclude:

- merely printing the shape set;
- reusing a previously selected set without reconsideration.

Task example: GLM 5.1 selects one shared set `[64, 128, 256, 384, 512, 640, 704, 2048]` after observing that independently optimized bucket shapes exceed the global limit, step 33.

### D4 — Parameter or configuration choice

The algorithm stays substantially the same, but the agent selects a numerical value, threshold, range, weight, bin width, or configuration.

Include:

- lambda or time-cost weights;
- padding or generation-length bin widths;
- merge penalties;
- grid-search ranges;
- choosing the final configuration from tested candidates.

Exclude:

- every individual iteration of an unchanged grid search;
- values fixed directly by the task specification;
- printed metrics that do not lead to a selection.

Task example: Claude Fable 5 performs a finer lambda grid search and selects a plan using constraint margins, step 10.

### D5 — Implementation or computational-efficiency choice

The agent chooses how to implement an already selected mathematical strategy, without fundamentally changing its objective.

Include:

- precomputing costs to make dynamic-programming transitions constant time;
- selecting a data structure or caching method;
- replacing an unnecessarily expensive inner-loop computation.

Exclude:

- ordinary file creation;
- syntax corrections with only one obvious repair;
- using a tool merely because it is the harness's available interface.

Task example: Gemini 3.1 Pro Preview with Terminus-2 decides to stop a slow implementation, precompute costs, and make the dynamic-programming transitions `O(1)`, step 9.

### D6 — Recovery or strategy revision

The agent changes a meaningful part of the approach in response to an error, failed constraint, inefficient result, or newly identified bottleneck.

Include:

- replacing an invalid shape-selection method;
- switching to targeted merging when sequential time remains too high;
- changing the optimizer after stale-candidate or coverage failures;
- revising the approach after a failed experiment.

Exclude:

- rerunning the same code without a change;
- correcting a typo or output format mechanically;
- observing a failure without selecting a response.

Task example: GLM 5.1 changes to targeted merges after observing that bucket 2 exceeds the sequential-time constraint even with zero decode padding, steps 18–24.

### D7 — Verification choice

The agent chooses a procedure or set of checks for establishing that the produced plan satisfies the task.

Include:

- independently validating coverage, thresholds, shapes, and output structure;
- deciding to perform a comprehensive final validation;
- adding a check motivated by a previously observed failure mode.

Exclude:

- simply reading an already available metric;
- reporting that validation passed;
- submitting without visible validation.

Task example: Claude Fable 5 independently checks coverage, all thresholds, and the global shape count, step 11.

### D8 — Termination or submission choice

The agent decides that further work is unnecessary and submits or marks the task complete.

Include:

- calling `mark_task_complete`;
- explicitly deciding that all constraints pass and the task is ready to finish.

Merge repeated confirmation calls into one event unless new evidence changes the decision.

Task example: Gemini 3.1 Pro Preview with Terminus-2 confirms `mark_task_complete` in steps 16–17. The decision is visible, but its reason is unavailable unless a preceding validation result supports it.

## 5. Primary-category tie-breaking

Use the following rules when multiple categories could apply:

1. If a failed result directly triggers a meaningful change, use `D6 Recovery or strategy revision` as primary.
2. If the main choice changes the batching or optimization method, use `D2 Algorithm or optimization strategy`.
3. If the algorithm stays fixed and only the global shape set changes, use `D3 Shape or representation choice`.
4. If only numeric values or search ranges change, use `D4 Parameter or configuration choice`.
5. If the mathematical approach stays fixed but its computational implementation changes, use `D5 Implementation or computational-efficiency choice`.
6. Use `D1 Diagnostic or analytical strategy` only when the information-gathering method is itself a meaningful choice.
7. Use `D7 Verification choice` for how success is checked and `D8 Termination or submission choice` for the subsequent decision to stop.

Example: “Sequential time is still too high, so use targeted greedy merges” is primarily `D6`, with `D2` as an optional secondary category.

## 6. Reason categories

Reasons describe why the agent made the decision. Multiple reason codes may be used, but one should be marked primary.

| Code | Reason category | Meaning |
|---|---|---|
| `R0` | No reason observable | The trajectory shows a choice but not why it was made. |
| `R1` | Task requirement or constraint | The choice is driven by an explicit threshold, output rule, or maximum-shape requirement. |
| `R2` | Empirical data evidence | The choice is driven by the observed request or length distribution. |
| `R3` | Cost-model or mathematical evidence | The choice is supported by formulas, lower bounds, or cost-model behaviour. |
| `R4` | Performance or efficiency | The choice aims to reduce cost, padding, latency, sequential time, runtime, or search cost. |
| `R5` | Correctness or validity | The choice aims to ensure coverage, valid output, correct grouping, or constraint satisfaction. |
| `R6` | Failure or unexpected result | An error, failed threshold, invalid shape set, or poor trial result triggers the choice. |
| `R7` | Simplicity or feasibility | The choice is made because it is simpler, tractable, or practical to implement. |
| `R8` | Environment, harness, or tool constraint | The choice responds to tool availability, dependency limitations, harness protocol, or execution limits. |

Do not assign `R4 Performance or efficiency` merely because the task concerns performance. The trajectory must connect the decision to a performance objective or observation.

## 7. Reason visibility

Reason category and reason visibility are separate fields.

| Value | Rule |
|---|---|
| `EXPLICIT` | The recorded thought or response states both the choice and why it is being made. |
| `CONTEXTUAL` | The reason is supported by nearby action/observation evidence, but the agent does not explicitly state it. This is an analyst inference. |
| `UNAVAILABLE` | A choice is visible, but the trajectory does not support a reason. Use `R0`. |

Examples:

- “Bucket 2 sequential time is the bottleneck, so use targeted merges” → `EXPLICIT`.
- A script tests several weight values and selects one after metrics are printed, but no thought explains the criterion → `CONTEXTUAL`.
- A harness submits the task with no visible validation or explanation → `UNAVAILABLE`.

## 8. Decision visibility and confidence

### 8.1 Decision visibility

| Value | Meaning |
|---|---|
| `STATED` | The thought or response explicitly describes the selected option. |
| `BEHAVIOURAL` | The selected option is visible only through actions or produced artifacts. |
| `AMBIGUOUS` | The action could represent either a new choice or execution of a previous choice. |

### 8.2 Annotation confidence

| Value | Rule |
|---|---|
| `HIGH` | Choice, event boundary, category, and evidence are clear. |
| `MEDIUM` | A choice is visible, but its boundary, category, or reason requires limited interpretation. |
| `LOW` | The event is retained as `UNCLEAR` because the available trajectory is insufficient. |

Missing thoughts should reduce confidence in the **reason**, not automatically in the existence of a decision when the action clearly implements a meaningful choice.

## 9. Required annotation fields

Each decision-event record should contain:

| Field | Description |
|---|---|
| `task_id` | `llm-inference-batching-scheduler` for this calibration round. |
| `trial_id` | Source trajectory identifier. |
| `model` | Normalized model name. |
| `harness` | Normalized harness name. |
| `resolved` | Task outcome from the normalized dataset. |
| `event_id` | Stable identifier within the trajectory. |
| `step_start` | First source step in the event. |
| `step_end` | Last source step in the event. |
| `decision_label` | `DECISION`, `NOT_DECISION`, or `UNCLEAR`. |
| `primary_category` | One of `D1`–`D8` for a decision. |
| `secondary_category` | Optional calibration field. |
| `decision_summary` | Short neutral description of the selected option. |
| `selected_option` | What the agent selected or changed. |
| `alternative_visible` | Alternative rejected or replaced, if recorded. |
| `primary_reason` | One of `R0`–`R8`. |
| `secondary_reasons` | Optional additional reason codes. |
| `reason_summary` | Neutral summary without adding unsupported motivation. |
| `decision_visibility` | `STATED`, `BEHAVIOURAL`, or `AMBIGUOUS`. |
| `reason_visibility` | `EXPLICIT`, `CONTEXTUAL`, or `UNAVAILABLE`. |
| `evidence_thought` | Exact relevant thought text, if present. |
| `evidence_action` | Exact relevant action text, if present. |
| `evidence_observation` | Exact relevant observation text, if present. |
| `confidence` | `HIGH`, `MEDIUM`, or `LOW`. |
| `annotator_note` | Brief explanation for ambiguous or merged events. |

Metadata such as model, harness, token usage, total steps, and completion time must not be used to infer a decision or reason. They are comparison variables added after annotation.

## 10. Event-boundary rules

1. **Thought followed by action:** Merge when the action implements the immediately preceding stated choice.
2. **Observation followed by revision:** Include the triggering observation and the later selected revision in the same event.
3. **Repeated parameter trials:** Group them as one event when the search policy is unchanged. Create a new event only when the search space, criterion, or strategy changes.
4. **Mechanical execution:** Do not extend an event through every command that merely implements the selected strategy. Retain only the steps needed to show the choice and its evidence.
5. **Repeated completion calls:** Merge confirmation calls into one termination event.
6. **Final summaries:** Use a final summary as supporting evidence only when it describes a choice visible elsewhere. Do not create duplicate decision events from the summary.

## 11. Negative examples for this task

The following are normally `NOT_DECISION` unless additional context shows a meaningful choice:

- listing task files;
- reading `cost_model.py` or `baseline_packer.py`;
- counting input records;
- creating the output directory;
- writing code after the strategy is already selected;
- rerunning an unchanged optimizer;
- printing or inspecting the final plan;
- updating a todo list without changing the technical approach;
- fixing an obvious file-format or syntax error;
- reporting metrics without selecting a response;
- restating the final solution in a summary.

## 12. Calibration examples from the six trajectories

| Trial/model/harness | Steps | Decision | Primary category | Primary reason | Reason visibility |
|---|---:|---|---|---|---|
| Claude Fable 5 / Claude Code | 6–10 | Use a per-sequence-level dynamic program and tune lambda values after analysing lower bounds and padding constraints. | `D2` | `R3` | `CONTEXTUAL` |
| Claude Fable 5 / Claude Code | 11 | Independently validate coverage, thresholds, sequential time, and global shapes. | `D7` | `R5` | `EXPLICIT` |
| GLM 5.1 / Claude Code | 18–24 | Replace the current formation method with targeted merges because bucket 2 sequential time remains above its threshold. | `D6` | `R6` | `EXPLICIT` |
| GLM 5.1 / Claude Code | 33–35 | Use one shared eight-shape set for both buckets. | `D3` | `R1` | `EXPLICIT` |
| Gemini 3.1 Pro Preview / Terminus-2 | 9–11 | Stop the slow dynamic program and precompute costs for constant-time transitions. | `D6` | `R4` | `EXPLICIT` |
| Gemini 3.1 Pro Preview / Terminus-2 | 16–17 | Confirm submission through the harness. | `D8` | `R0` | `UNAVAILABLE` |
| Gemini 3.1 Pro Preview / Gemini CLI | 16–17 | Test the effect of shape choice and shape reuse before fixing the grouping strategy. | `D1` | `R3` | `CONTEXTUAL` |
| Muse Spark 1.1 / mini-swe-agent | 11–29 | Conduct repeated batching-parameter trials. Treat the sequence as one search event unless the search policy visibly changes. | `D4` | `R0` | `UNAVAILABLE` |

These examples are provisional. During the first annotation pass, their event boundaries and labels should be checked against the full untruncated trajectory text.

## 13. Annotation procedure

For each trajectory:

1. Read the task requirements and the complete trajectory once without annotating.
2. Mark candidate steps where an option appears to be selected, rejected, prioritized, or changed.
3. Apply the three-part choice test.
4. Label candidates as `DECISION`, `NOT_DECISION`, or `UNCLEAR`.
5. Merge adjacent steps into decision events using the boundary rules.
6. Assign one primary decision category.
7. Record the selected option and any visible alternative.
8. Copy exact evidence from thought, action, and observation.
9. Assign reason category and reason visibility independently.
10. Assign confidence and add a short note only when needed.
11. Perform a second pass to remove duplicate events created by repeated commands or final summaries.

## 14. Cross-harness safeguards

- Apply the same choice test to every harness.
- Do not interpret more tool calls as more decisions.
- Do not interpret longer thoughts as better reasoning.
- Do not penalize a harness simply because thoughts are missing; mark reason visibility accurately.
- Do not treat harness warnings, tool confirmations, or metadata as agent decisions.
- Keep `STATED` and `BEHAVIOURAL` decisions separate in analysis because harnesses expose different amounts of reasoning text.
- Compare decision counts only after event merging.

## 15. Open calibration questions

The following questions should be resolved before this codebook is frozen:

1. Should diagnostic experiments (`D1`) be included in the thesis definition of design decisions, or analysed as a separate planning category?
2. Should mechanical parameter sweeps count as one behavioural decision when no thought states the search policy?
3. Should `D8 Termination` be included with design decisions or reported separately as agent-control behaviour?
4. Should secondary decision categories remain in the gold dataset or be removed after calibration?
5. How much nearby context may be used to assign `CONTEXTUAL` reasons: the event span, a fixed step window, or the whole trajectory?

## 16. Versioning rule

Any change to a category definition, decision boundary, or evidence rule must be recorded before annotations are updated. This file remains `v1` during calibration; dated revisions may be listed below.

### Revision log

| Date | Revision | Description |
|---|---|---|
| 2026-08-23 | `v1-draft.1` | Initial task-specific codebook derived from six resolved `llm-inference-batching-scheduler` trajectories. |
