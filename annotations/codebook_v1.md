# Design-Decision Codebook v1

## Design decision

A **design decision** is an observable choice between plausible approaches that
affects how a task is investigated or solved, how the solution is structured or
implemented, or how its correctness, performance, or completion is assessed.

The choice must be supported by the recorded text, actions, or code. Alternatives
need not be explicitly discussed, and the agent does not need to explain why it
made the choice. Do not invent alternatives, reasoning, or intentions that the
trajectory does not support.


## Decision visibility

- **Explicit:** The agent clearly states the particular choice in its own
  explanation, for example, "I will use dynamic programming."
- **Contextual:** The choice is supported by the agent's code or actions but is
  not clearly stated in its explanation.

Visibility describes how the choice is expressed, not whether its reason is
explained. Use only these two values for supported design decisions.


## Annotation fields

- **Design decision:** A brief description of the particular choice made.
- **Design label:** A concise, descriptive name for that choice.
- **Taxonomy category:** The best-fitting category, D1–D8.
- **Visibility:** Explicit or Contextual.

If several distinct decisions occur in one spreadsheet row, place each decision
on a separate line within the existing cells. Keep the decision, label, category,
and visibility lines aligned so that each line refers to the same decision.

## Taxonomy

The examples below are illustrative. Assign the category that best describes the
supported choice; a trajectory does not need to contain every category.

### D1 — Diagnostic or analytical strategy

**Definition:** Choosing how to investigate the problem, identify its cause, or
collect information needed to select an approach.

**Example:** Run a focused profiling experiment to identify which stage causes
the slowdown before deciding what to optimize.

### D2 — Algorithm or optimization strategy

**Definition:** Choosing the computational, mathematical, or search method used
to solve the problem.

**Example:** Use dynamic programming rather than exhaustive enumeration to
partition requests into batches.

### D3 — Representation or architecture choice

**Definition:** Choosing how data, state, components, or interfaces are structured
and related.

**Example:** Separate parsing, validation, and execution into distinct components
rather than placing all logic in one function.

### D4 — Parameter or configuration choice

**Definition:** Selecting a value, threshold, range, or operational setting while
keeping the main approach unchanged.

**Example:** Compare several batch sizes and select one that fits the memory
limit while maintaining throughput.

### D5 — Implementation or computational-efficiency choice

**Definition:** Choosing how to implement an established approach, including
libraries, tools, caching, precomputation, or memory management, without changing
the underlying solving method.

**Example:** Precompute prefix sums so a dynamic-programming solver can calculate
candidate-batch totals without repeatedly scanning the same requests.

### D6 — Recovery or strategy revision

**Definition:** Changing the approach in response to an error, failed requirement,
poor result, or newly discovered obstacle. Use this category when the record
connects the revision to that triggering result.

**Example:** Replace a regex-based parser after a failing test shows that it
cannot handle nested expressions.

### D7 — Verification choice

**Definition:** Choosing how to check whether a candidate solution is correct,
complete, compatible, or sufficiently performant.

**Example:** Compare the outputs of the original and optimized SQL queries to
check that the optimization preserves the results.

### D8 — Termination or submission choice

**Definition:** Deciding that the available result is sufficient to stop further
work, submit the solution, or hand it back as complete.

**Example:** Stop the parameter search and submit after a candidate satisfies all
required constraints and the selected validation checks pass.


## Annotation rules

1. **Read the whole trajectory, then examine every step.** Use the task
   description and the information recorded in the Thought, Action, and
   Observation columns to identify supported choices throughout the process,
   not just the main solution.
2. **Keep trajectories independent.** Use evidence from the current trajectory
   only. Apply the same codebook without carrying over another trajectory's
   solution or annotations.
3. **Identify trajectories by Trial ID.** Each trajectory has a unique Trial ID.
4. **Annotate agent-made choices not directly specified in the task.** If the
   agent simply executes an approach directly specified in the task description,
   do not annotate that execution as a design decision. Annotate supported choices
   the agent makes that are not directly specified, including choices about the
   approach, parameters, or implementation. Do not apply a size or importance
   threshold to those choices.
5. **Allow multiple decisions within a step.** One step may contain several
   decisions. Do not annotate an exact repetition of the same design decision
   again. Leave cells empty where no decision is supported, and do not force an
   annotation when a decision is unclear.
