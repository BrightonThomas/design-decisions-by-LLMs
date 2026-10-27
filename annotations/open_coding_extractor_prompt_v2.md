# Open-coding decision extractor prompt v2

You are extracting observable design-decision events from a recorded coding-agent trajectory.

## Unit of analysis

A design decision is a **bounded choice**, not a trajectory summary. Record an event when the trace shows the agent selecting, rejecting, prioritizing, revising, or terminating a meaningful course of action that could affect the solution approach, implementation, correctness, performance, verification, or completion.

Include an event only when all three conditions are supported:

1. **Selection:** the agent selects, rejects, prioritizes, or changes an option.
2. **Alternative:** another plausible option could have been selected.
3. **Consequence:** the choice could materially affect later execution or the result.

Scan the complete trajectory chronologically and return **every distinct qualifying decision**. A trajectory may contain zero, one, or several decisions. Do not collapse an entire trajectory into one broad event when separate choices occur at different points.

## Event boundaries

- Merge adjacent thought, action, and observation steps only when they support one unchanged choice.
- Start a new event when the algorithm, representation, implementation method, parameter policy, recovery strategy, verification method, or stopping decision changes.
- Keep `source_steps` minimal: include every step needed to support the choice, but do not automatically include all steps from the beginning to the end of the trajectory.
- Repeated commands that mechanically implement an earlier choice are not new decisions.
- A parameter sweep under one unchanged search policy is one event; choosing or revising the policy can be another event.
- Inspection is a decision only when the trace supports a meaningful choice of diagnostic strategy.
- Do not repeat a decision merely because it is restated in a final answer.
- Do not infer private reasoning that is absent from the record.

## Output fields

For every event return:

- `source_steps`: the minimal ordered list of supporting step numbers;
- `decision_summary`: one neutral sentence stating the selected course of action and, when visible, the relevant alternative;
- `decision_type_label`: a task-independent 2–8 word action–object label;
- `visibility`: `EXPLICIT`, `CONTEXTUAL`, or `UNAVAILABLE`.

Avoid labels that merely restate the task or outcome, such as “solve task,” “implement solution,” or “task completion strategy.” Generate labels freely; do not use or assume a predefined taxonomy.

Visibility rules:

- `EXPLICIT`: recorded text directly states the selected option.
- `CONTEXTUAL`: the selected option is defensibly identifiable from code, actions, or tool use without a direct statement.
- `UNAVAILABLE`: the available trace does not establish a defensible choice. Do not create a decision event from speculation.

## Synthetic example 1: multiple decisions in one trajectory

Input excerpt:

- Step 2 thought: “Enumerating every schedule is exponential, so I will use dynamic programming over completed jobs and elapsed time.”
- Step 3 action: implements the dynamic-programming scheduler.
- Step 7 observation: small examples pass, but tie handling is uncertain.
- Step 8 thought: “I will compare the solver with exhaustive enumeration on small random instances.”
- Step 9 action: runs the exhaustive cross-check.

Expected decisions:

```json
{
  "decisions": [
    {
      "source_steps": [2, 3],
      "decision_summary": "Selected dynamic programming over exhaustive schedule enumeration to control combinatorial growth.",
      "decision_type_label": "dynamic-programming scheduling",
      "visibility": "EXPLICIT"
    },
    {
      "source_steps": [7, 8, 9],
      "decision_summary": "Selected exhaustive small-instance comparison to validate the optimized scheduler's tie handling.",
      "decision_type_label": "exhaustive reference validation",
      "visibility": "EXPLICIT"
    }
  ]
}
```

These are two decisions because the algorithm choice and the verification-method choice have different alternatives and consequences.

## Synthetic example 2: strategy revision after failure

Input excerpt:

- Step 4 action: attempts to install a parsing library.
- Step 5 observation: installation fails because network access is unavailable.
- Step 6 thought: “I will avoid the dependency and implement the parser with the standard library.”
- Steps 7–9 actions: implement and run the standard-library parser.

Expected decision:

```json
{
  "decisions": [
    {
      "source_steps": [4, 5, 6, 7],
      "decision_summary": "Replaced the unavailable parsing dependency with a standard-library implementation.",
      "decision_type_label": "dependency-free parser fallback",
      "visibility": "EXPLICIT"
    }
  ]
}
```

Steps 8–9 are mechanical continuation unless they introduce another meaningful choice.

## Output contract

Return only one JSON object matching this structure:

```json
{
  "decisions": [
    {
      "source_steps": [0],
      "decision_summary": "...",
      "decision_type_label": "...",
      "visibility": "EXPLICIT"
    }
  ]
}
```

Use `{"decisions": []}` only when no recorded event satisfies the decision test.

## Task and trajectory

{{TRAJECTORY_JSON}}
