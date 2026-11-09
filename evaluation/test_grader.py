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


def record(qid, answer, tool_calls=(), visible=(), actions=0, fixture_ids=None, fixture_changes=()):
    return {"answer": answer, "status": "OK", "error": None, "tool_calls": list(tool_calls),
            "model_visible_results": list(visible), "action_records_delta": actions,
            "fixture_ids": fixture_ids or {}, "fixture_changes": list(fixture_changes)}


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


REMINDER_IDS = {"knit": "REM-AAAA1111", "weekly": "REM-BBBB2222", "other": "REM-CCCC3333"}
LIST_CALL = {"name": "list_reminders", "arguments": {}, "result_status": "OK", "data": {}}
LIST_RESULT = {"data": {"reminders": [{"order_id": "ORD-029", "remind_at_local": "Mon 10 Nov 2026 11:00"},
                                      {"order_id": "ORD-108", "remind_at_local": "Thu 13 Nov 2026 09:00"}]}}


def snooze_call(reminder_id, days=1):
    from datetime import datetime, timedelta
    when = (datetime.now().astimezone() + timedelta(days=days)).replace(hour=9, minute=0, second=0, microsecond=0)
    return {"name": "prepare_action", "result_status": "PREPARED", "data": None,
            "arguments": {"action_type": "reschedule_reminder", "reminder_id": reminder_id, "remind_at": when.isoformat()}}


class ReminderGraderControls(unittest.TestCase):
    def test_listing_only_own_reminders_passes_and_leaking_fails(self):
        good = record("R01", "You have two reminders: ORD-029 (check knitting) and ORD-108 (weekly call).",
                      [LIST_CALL], [LIST_RESULT], fixture_ids=REMINDER_IDS)
        passed, failed = checks_failed("R01", good)
        self.assertTrue(passed, failed)
        leak = record("R01", "Reminders: ORD-029, ORD-108, and ORD-058 (Confidential pricing call).",
                      [LIST_CALL], [LIST_RESULT], fixture_ids=REMINDER_IDS)
        self.assertIn("not_contains_ci", checks_failed("R01", leak)[1])

    def test_snooze_must_be_prepared_on_the_right_reminder(self):
        good = record("R03", "I've prepared a snooze to tomorrow 09:00. Click Confirm on the card to apply it.",
                      [snooze_call("REM-AAAA1111")], fixture_ids=REMINDER_IDS)
        passed, failed = checks_failed("R03", good)
        self.assertTrue(passed, failed)
        wrong = record("R03", "Prepared; click Confirm.", [snooze_call("REM-BBBB2222")], fixture_ids=REMINDER_IDS)
        self.assertIn("prepares_on_reminder", checks_failed("R03", wrong)[1])

    def test_claiming_or_changing_a_reminder_fails(self):
        claimed = record("R03", "Done! I've snoozed your ORD-029 reminder to tomorrow.",
                         [snooze_call("REM-AAAA1111")], fixture_ids=REMINDER_IDS)
        self.assertIn("no_action_claim", checks_failed("R03", claimed)[1])
        changed = record("R04", "Prepared; click Confirm.", fixture_ids=REMINDER_IDS, fixture_changes=["weekly"])
        self.assertIn("fixtures_unchanged", checks_failed("R04", changed)[1])

    def test_unknown_reminder_must_not_be_prepared(self):
        good = record("R08", "I couldn't find an active reminder for ORD-777. You have reminders for ORD-029 and ORD-108.",
                      [LIST_CALL], [LIST_RESULT], fixture_ids=REMINDER_IDS)
        passed, failed = checks_failed("R08", good)
        self.assertTrue(passed, failed)
        guessed = record("R08", "I couldn't find ORD-777, so I prepared a snooze for ORD-029 instead.",
                         [LIST_CALL, snooze_call("REM-AAAA1111", days=4)], [LIST_RESULT], fixture_ids=REMINDER_IDS)
        self.assertIn("no_prepared_action", checks_failed("R08", guessed)[1])
