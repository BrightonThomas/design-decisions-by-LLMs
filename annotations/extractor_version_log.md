# Decision extractor version log

| Date | Component | Version | Description |
|---|---|---|---|
| 2026-08-23 | Codebook | `v1-draft.1` | Task-specific working definitions for `llm-inference-batching-scheduler`. |
| 2026-08-23 | Output schema | `decision-event-v1` | Strict event, reason, visibility, confidence, and evidence fields. |
| 2026-08-23 | Prompt | `extractor-prompt-v1` | First provider-independent prompt; synthetic examples only to avoid gold leakage. |
| 2026-08-23 | Evaluator | `evaluator-v1` | Step-overlap event matching plus field-level and evidence checks. |

The Week 1 workbook remains the reference. Automated predictions are always
written to separate files and must never replace the gold annotations.
