# Design-Decision Codebook V2

## Design decision

A design decision is an observable choice between plausible approaches that affects how a task is investigated, solved, structured, implemented, verified, or completed. Alternatives need not be stated, but the selected choice must be supported by recorded thoughts, actions, or code. Do not invent alternatives the agent considered, intentions, or reasons.

Count meaningful choices, not every command. Exclude mechanical execution of an earlier choice, unchanged repetitions, results alone, obvious syntax fixes, and choices fully prescribed by the task. A required outcome can still leave meaningful freedom in how to achieve it. One decision may span several steps, and one step may contain several distinct decisions.

## Taxonomy

Assign one primary category per decision. Classify the particular choice rather than its task name, tool name, or position in the trajectory. Categories describe the role of a choice, not whether its impact is major or minor.

### D1 — Diagnostic or analytical strategy

**Definition:** Choosing how to investigate the problem, identify a cause, assess feasibility, or gather information needed to select an approach.

**Boundary:** The purpose is to understand the problem or inform a later solution choice. Use D7 when assessing an existing candidate solution against requirements. Reading files or running a command is not automatically D1: the record must support a meaningful investigation, such as locating missing work, identifying a bottleneck, or examining assumptions. A diagnostic action following an error remains D1 unless it also contains a distinct solution revision.

**Example:** An agent must recover changes that disappeared after switching to the main Git branch. It inspects the HEAD reflog, branches, and stashes, then examines the detached commit's changes and compares them with the current branch. These actions form an investigation that locates the missing work and establishes what needs to be recovered. The diagnostic choice is D1; the later merge is a separate choice. The task's recovery objective does not make the initial investigation D6.

### D2 — Algorithm or optimization strategy

**Definition:** Choosing the computational, mathematical, search, or transformation method that produces the solution.

**Boundary:** D2 concerns how the result is computed. Use D3 for representation and structural relationships, D4 for settings within a method, and D5 for implementing an established method. A performance improvement is not automatically D2: determine whether it changes the solving method or implements the same method more efficiently. When an earlier method is meaningfully revised in response to an error or poor result, use D6 for that revision.

**Example:** To schedule LLM requests, the agent groups requests by aligned prompt length and sorts their generation lengths. It chooses dynamic programming to partition these into contiguous batches, optimizing cost with weighted latency and padding terms while applying a latency guard. The choice of DP partitioning is D2. Selecting the penalty values is a separate D4 choice, and accelerating range calculations with prefix sums is a separate D5 choice.

### D3 — Representation or architecture choice

**Definition:** Choosing the representation of data or intermediate results, or the architecture that organizes state, components, ownership, lifetimes, and interfaces. Representations can include tables, matrices, tensors, graphs, and structured records.

**Boundary:** D3 concerns what information is represented and how its elements or components relate. D2 concerns the method that computes with that representation, D4 its operational settings, and D5 the technique used to implement an established method. Choosing a table, tensor, or graph is D3 when the record supports a meaningful representation choice; the mere presence of an array or table in code is insufficient. Similarly, creating files or importing libraries does not establish an architectural decision. Do not count every incidental data structure as a separate D3 event.

**Example:** A calculation contains operations that depend on the results of other operations. The agent chooses to represent these dependencies as a directed graph: each node represents an operation, each edge represents a prerequisite relationship, and adjacency lists store the connections. This makes dependency relationships explicit and available for determining a valid execution order. Choosing this graph representation is D3. Choosing topological sorting to compute the execution order is a separate D2 decision; choosing a library to implement that established method is D5.

### D4 — Parameter or configuration choice

**Definition:** Selecting a value, threshold, range, mode, or operational setting within an established approach.

**Boundary:** The main method and structural arrangement remain unchanged. A parameter can have major consequences and still be D4. Count a planned parameter search and its selection as one event rather than treating every candidate value as a new decision. A meaningful revision to an earlier selected configuration following unexpected evidence can be D6; unsuccessful candidates within an unchanged planned search do not automatically qualify. Values dictated by the task are not discretionary choices.

**Example:** While implementing a gRPC key-value server, the agent configures its thread pool with max_workers=10. This selects the worker-count setting without changing the RPC contract, storage behavior, or underlying server approach. The particular worker count is D4; choosing the execution mechanism would be a separate implementation choice if supported. The required port number is not another D4 decision because the task fixes it.

### D5 — Implementation or computational-efficiency choice

**Definition:** Choosing how to implement or execute an established approach without changing its underlying solving method. This includes implementation tools, libraries, caching, precomputation, memory access, and execution techniques.

**Boundary:** D5 is not a general category for writing code. Use D2 when the computation or solving method changes, D3 when the choice establishes structural relationships, and D4 when it selects a setting. Ordinary code writing after choosing an implementation technique is execution of that decision. A meaningful change to an earlier implementation in response to a failure or poor result is D6.

**Example:** A batching solver already uses DP to evaluate contiguous request groups. The agent precomputes prefix sums of request counts and count-weighted generation lengths, allowing each candidate group's totals to be obtained from differences between prefix values. This avoids repeatedly scanning the group's members while preserving the DP partitioning method. The precomputation choice is D5, rather than another D2 event simply because it improves runtime.

### D6 — Recovery or strategy revision

**Definition:** Meaningfully revising an earlier solution choice in response to an error, failed requirement, poor result, or newly discovered obstacle. The revised choice may concern an algorithm, architecture, representation, parameter, or implementation.

**Boundary:** Identify three connected elements: the earlier choice, the triggering evidence, and the changed choice. Their connection can be stated directly or clearly supported by the recorded sequence. D6 takes precedence over D2–D5 for the same responsive revision; describe the aspect changed without assigning a second category to that event. An error alone, a rerun, an investigation, or re-verification is not D6. A recovery-themed task does not establish revision of an earlier agent choice. Routine syntax fixes and mechanical compliance with tool instructions are insufficient.

**Example:** The agent initially batches requests with exactly matching aligned prompt and generation lengths. Evaluation shows that this produces too many batches and exceeds the sequential-time limit, although cost is acceptable. The agent acknowledges this trade-off and introduces greedy merging of generation groups to balance time and cost. This is D6 because the record connects an earlier algorithmic choice, an inadequate result, and a meaningful change. The revision is recorded once as D6; evaluating the new candidate is a separate D7 choice when supported.

### D7 — Verification choice

**Definition:** Choosing how to assess whether a candidate solution is correct, complete, compatible, or sufficiently performant against the requirements.

**Boundary:** D7 concerns the selected assessment procedure, property, or test coverage. The result of a check is evidence, not another decision. Use D1 when gathering information to understand the problem or select an approach, D6 when changing the solution in response to a check, and D8 when accepting the result or stopping. Repeating an unchanged check does not automatically create a new D7 event; identify any distinct assessment choice.

**Example:** After implementing an async helper, the agent chooses to test actual keyboard-interrupt behavior rather than rely only on a concurrency test. It runs the helper in a subprocess, sends a real SIGINT, and checks that started jobs complete their asynchronous cleanup before KeyboardInterrupt reaches the caller. This is D7 because it selects a procedure that assesses a specific requirement of the candidate. The observed cleanup output supports the assessment but is not another decision.

### D8 — Termination or submission choice

**Definition:** Deciding to stop further work, accept the current result, submit, or hand back the solution as complete.

**Boundary:** D8 is the stopping or acceptance choice, not the preceding validation. The record must support an observable acceptance or handoff; a passing test or the absence of later steps alone is insufficient. Count the stopping event once and do not recreate earlier choices from a final summary. A stopping decision can occur with acknowledged limitations or failed checks, so success is not required. Do not force D8 into an interrupted or unfinished trajectory.

**Example:** The agent benchmarks a portfolio implementation at both 5,000 and 8,000 assets, checking numerical agreement with the baseline and the required speed improvement. After the checks pass, it accepts the implementation and hands back the completed solution with the results. Choosing the benchmark is D7; accepting and handing back the result is D8. The final explanation of the implementation does not create duplicate algorithm or implementation decisions.

## Visibility

- **Explicit:** The particular choice is clearly stated in agent-authored natural language, ideally Thought. An extremely clear topmost code comment block or opening module docstring also qualifies; a generic announcement of coding does not.
- **Contextual:** The choice must be identified from commands, code, edits, or their relationship to observations. Internal, inline, or short local comments remain Contextual unless qualifying natural language elsewhere directly states the choice.

## Annotation rules

- Read the task and complete trajectory in recorded order. Apply the same rules to successful and failed runs; do not use outcome or model identity to infer decisions.
- Record each decision once where it first becomes supported, including supporting step numbers. Merge its stated plan and implementation if required, and include any later explanation as evidence without creating a duplicate.
- Keep distinct investigation, solution revision, verification, and stopping choices separate. For D6, include the earlier choice and trigger in the supporting steps.
- Record a concrete **Design decision**, a concise reusable **Design label**, one **Taxonomy category** (D1–D8), and **Visibility** (Explicit or Contextual). Leave unsupported or unclear candidates unannotated rather than inventing evidence or a third visibility label.
- In the workbook, write in these fields to J–M. For multiple decisions on one row, use aligned newline-separated entries. Leave rows without decisions blank and preserve all original trajectory data.
