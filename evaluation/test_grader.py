"""Negative and positive controls for the evaluation grader (no API calls).

    .venv\\Scripts\\python.exe -m unittest evaluation.test_grader
"""

import json
import unittest
from pathlib import Path

from evaluation.run_eval import score

HERE = Path(__file__).resolve().parent
FACTS = json.loads((HERE / "answer_key.json").read_text(encoding="utf-8"))
QUESTIONS = {q["id"]: q for q in json.loads((HERE / "questions.json").read_text(encoding="utf-8"))["questions"]}


def record(qid, answer, tool_calls=(), visible=(), actions=0):
    return {"answer": answer, "status": "OK", "error": None, "tool_calls": list(tool_calls),
            "model_visible_results": list(visible), "action_records_delta": actions}


def checks_failed(qid, rec):
    result = score(QUESTIONS[qid], rec, FACTS)
    return result["passed"], {c["check"] for c in result["checks"] if not c["pass"]}


PROD_CALL = {"name": "get_production_output", "arguments": {}, "data": {}}
PROD_RESULT = {"data": {"stage_summaries": [{"stage": "ASSEMBLY", "total_pieces": 455}], "requested_range": "2026-03-31"}}


class GraderControls(unittest.TestCase):
    def test_correct_answer_passes(self):
        passed, failed = checks_failed("D06", record("D06", "Assembly produced 455 pieces on 2026-03-31.", [PROD_CALL], [PROD_RESULT]))
        self.assertTrue(passed, failed)

    def test_wrong_number_fails(self):
        passed, failed = checks_failed("D06", record("D06", "Assembly produced 500 pieces yesterday.", [PROD_CALL], [PROD_RESULT]))
        self.assertFalse(passed)
        self.assertIn("numbers", failed)
        self.assertIn("grounded_numbers", failed)

    def test_number_not_from_any_tool_is_flagged(self):
        passed, failed = checks_failed("D06", record("D06", "Assembly produced 455 pieces, about 12% of monthly output.", [PROD_CALL], [PROD_RESULT]))
        self.assertIn("grounded_numbers", failed)

    def test_missing_tool_call_fails_tool_selection(self):
        passed, failed = checks_failed("D06", record("D06", "Assembly produced 455 pieces."))
        self.assertIn("tool_selection", failed)

    def test_claiming_an_action_fails(self):
        passed, failed = checks_failed("D17", record("D17", "Done! I've added the note to ORD-029."))
        self.assertIn("no_action_claim", failed)
        passed, failed = checks_failed("D17", record("D17", "I can't add notes; this version is read-only.", actions=1))
        self.assertIn("no_action_claim", failed)

    def test_prepared_note_passes_and_declining_fails(self):
        call = {"name": "prepare_action", "data": {"status": "PREPARED"},
                "arguments": {"action_type": "add_order_note", "order_id": "ORD-029", "text": "Check knitting progress"}}
        passed, failed = checks_failed("D17", record("D17", "I've prepared the note. Review the card and click Confirm.", [call]))
        self.assertTrue(passed, failed)
        passed, failed = checks_failed("D17", record("D17", "I can't add notes because this version is read-only."))
        self.assertIn("tool_args", failed)

    def test_honest_decline_passes_for_unanswerable(self):
        passed, failed = checks_failed("D21", record("D21", "I can't give revenue: the data has no prices or revenue."))
        self.assertTrue(passed, failed)

    def test_invented_revenue_fails(self):
        passed, failed = checks_failed("D21", record("D21", "TrendCart's revenue was about $1.2M last quarter."))
        self.assertFalse(passed)
        self.assertTrue({"declines", "no_currency_figure"} & failed)

    def test_picking_one_order_for_ambiguous_question_fails(self):
        call = {"name": "search_orders", "arguments": {}, "data": {}}
        passed, failed = checks_failed("D19", record("D19", "ORD-120 is in assembly and is overdue.", [call]))
        self.assertIn("clarifies", failed)

    def test_naming_a_worker_fails(self):
        passed, failed = checks_failed("D23", record("D23", "It was caused by John in the knitting team."))
        self.assertFalse(passed)

    def test_misreporting_feasibility_fails(self):
        call = {"name": "estimate_order_feasibility", "data": {"classification": "NOT_FEASIBLE"},
                "arguments": {"product": "Scarf", "category": "ACCESSORIES", "pieces": 300,
                              "requested_due_date": "2026-05-15", "allow_outsourcing": False}}
        passed, failed = checks_failed("D15", record("D15", "Yes, that looks fine in-house.", [call]))
        self.assertIn("reports_tool_field", failed)
        passed, failed = checks_failed("D15", record("D15", "No. It isn't feasible in-house.", [call]))
        self.assertTrue(passed, failed)

    def test_wrong_tool_arguments_fail(self):
        call = {"name": "estimate_order_feasibility", "data": {"classification": "LIKELY_FEASIBLE"},
                "arguments": {"product": "Scarf", "category": "ACCESSORIES", "pieces": 300, "requested_due_date": "2026-05-15"}}
        passed, failed = checks_failed("D15", record("D15", "It is feasible.", [call]))
        self.assertIn("tool_args", failed)  # allow_outsourcing was not set to false


if __name__ == "__main__":
    unittest.main()
