# Week 2 decision extractor

This package turns complete trajectory records into strict, machine-readable
design-decision events and compares them with the Week 1 gold annotations.

## What is automated

1. Select trajectories without loading the whole Terminal-Bench file into memory.
2. Build the versioned prompt and JSON schema.
3. Send the prompt to an explicitly supplied model command, or prepare an outbox.
4. Reject malformed labels, impossible steps, and evidence not found in the source.
5. Match predicted and gold events by source-step overlap.
6. Report event precision/recall/F1, category accuracy, reason visibility,
   primary reason, event boundary accuracy, and a row-level error table.

The tool does not infer missing thoughts. Model and harness names are included as
metadata but the prompt forbids using them as annotation evidence.

## Files

- `annotations/decision_event_schema_v1.json`: strict output contract.
- `annotations/extractor_prompt_v1.md`: provider-independent prompt.
- `annotations/extractor_version_log.md`: version history.
- `outputs/2026-08-23_week2_decision_extractor/`: fixed pilot inputs and results.
- `notebooks/week2_decision_extractor_validation.ipynb`: simple validation report.

## Rebuild the fixed pilot export

Run from the `design-decisions-by-LLMs` repository root:

```powershell
python -m zest.decision_extractor.prepare_week2_assets `
  --gold-workbook outputs/2026-08-23_llm_batching_gold_annotations/llm_batching_gold_annotations_v1.xlsx `
  --source-workbook outputs/llm_batching_annotations/llm_inference_batching_scheduler_trajectory_annotations.xlsx `
  --output-dir outputs/2026-08-23_week2_decision_extractor
```

## Prepare prompts without calling a model

```powershell
python -m zest.decision_extractor.extract `
  --input outputs/2026-08-23_week2_decision_extractor/pilot_trajectories_two.jsonl `
  --output outputs/2026-08-23_week2_decision_extractor/pilot_prompt_outbox.jsonl `
  --schema annotations/decision_event_schema_v1.json `
  --prompt annotations/extractor_prompt_v1.md `
  --provider outbox
```

## Run with an LLM command

The command must read the prompt from standard input and print only the JSON
response. Arguments are supplied as a JSON array and are executed without a shell.
For example, after choosing and authenticating a provider:

```powershell
python -m zest.decision_extractor.extract `
  --input outputs/2026-08-23_week2_decision_extractor/pilot_trajectories_two.jsonl `
  --output outputs/2026-08-23_week2_decision_extractor/pilot_predictions_live.jsonl `
  --schema annotations/decision_event_schema_v1.json `
  --prompt annotations/extractor_prompt_v1.md `
  --provider command `
  --command-json '["YOUR_LLM_COMMAND", "YOUR_NONINTERACTIVE_ARGUMENT"]' `
  --model-name YOUR_MODEL
```

No live provider is selected by default, preventing accidental API or subscription
usage. The included `gold_replay` run is only a pipeline test; its perfect score
must never be reported as model accuracy.

## Evaluate predictions

```powershell
python -m zest.decision_extractor.evaluate `
  --gold outputs/2026-08-23_week2_decision_extractor/pilot_gold_events_two.jsonl `
  --predictions outputs/2026-08-23_week2_decision_extractor/pilot_predictions_live.jsonl `
  --summary outputs/2026-08-23_week2_decision_extractor/live_validation_summary.json `
  --matches outputs/2026-08-23_week2_decision_extractor/live_event_matches.csv `
  --errors outputs/2026-08-23_week2_decision_extractor/live_error_analysis.csv
```

The default event match threshold is 0.5 using overlap coefficient:
`shared steps / min(gold steps, predicted steps)`. Matching is one-to-one and
greedy, ordered first by overlap and then by category agreement.
