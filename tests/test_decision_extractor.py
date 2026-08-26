from __future__ import annotations

import unittest

from zest.decision_extractor.core import validate_extraction
from zest.decision_extractor.evaluate import evaluate_records


def trajectory() -> dict:
    return {
        "task_id": "task",
        "trial_id": "trial",
        "model": "model",
        "harness": "harness",
        "resolved": True,
        "steps": [
            {"step": 0, "thought": "The broad test failed, so run the parser test.", "action": "pytest parser", "observation": "1 passed"},
            {"step": 1, "thought": None, "action": "submit", "observation": None},
        ],
    }


def event() -> dict:
    return {
        "event_id": "P01",
        "source_steps": [0],
        "primary_category": "D6",
        "secondary_category": None,
        "decision_summary": "Use a targeted parser test.",
        "selected_option": "Run the parser test.",
        "alternative_visible": "Continue with the broad test.",
        "primary_reason": "R6",
        "secondary_reasons": [],
        "reason_summary": "The broad test failed.",
        "decision_visibility": "STATED",
        "reason_visibility": "EXPLICIT",
        "confidence": "HIGH",
        "evidence": [{"step": 0, "field": "thought", "excerpt": "The broad test failed"}],
    }


class ValidationTests(unittest.TestCase):
    def test_valid_event(self) -> None:
        extraction = {"schema_version": "decision-event-v1", "task_id": "task", "trial_id": "trial", "events": [event()]}
        self.assertEqual(validate_extraction(extraction, trajectory()), [])

    def test_fabricated_evidence_is_rejected(self) -> None:
        bad_event = event()
        bad_event["evidence"] = [{"step": 0, "field": "thought", "excerpt": "invented text"}]
        extraction = {"schema_version": "decision-event-v1", "task_id": "task", "trial_id": "trial", "events": [bad_event]}
        codes = {error["code"] for error in validate_extraction(extraction, trajectory())}
        self.assertIn("unsupported_evidence", codes)

    def test_unavailable_reason_requires_r0(self) -> None:
        bad_event = event()
        bad_event["reason_visibility"] = "UNAVAILABLE"
        extraction = {"schema_version": "decision-event-v1", "task_id": "task", "trial_id": "trial", "events": [bad_event]}
        codes = {error["code"] for error in validate_extraction(extraction, trajectory())}
        self.assertIn("unsupported_reason", codes)


class EvaluationTests(unittest.TestCase):
    def test_event_and_field_metrics_are_separate(self) -> None:
        gold_event = event()
        gold_event["event_id"] = "G01"
        predicted_event = event()
        predicted_event["primary_category"] = "D2"
        gold = [{"trial_id": "trial", "events": [gold_event]}]
        predictions = [{
            "trial_id": "trial", "valid": True, "errors": [],
            "extraction": {"events": [predicted_event]},
        }]
        summary, _, errors = evaluate_records(gold, predictions)
        self.assertEqual(summary["event_f1"], 1.0)
        self.assertEqual(summary["category_accuracy_on_matches"], 0.0)
        self.assertIn("wrong_category", {row["error_type"] for row in errors})


if __name__ == "__main__":
    unittest.main()

