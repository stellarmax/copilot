import csv
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from backend.copilot import CopilotCore


ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"


class CopilotCoreTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.data_dir = self.root / "data"
        shutil.copytree(ROOT / "demo_data", self.data_dir)
        self.core = CopilotCore(self.data_dir, self.root / "test.sqlite3", BACKEND / "rules_config.json")

    def tearDown(self):
        self.core.close()
        self.temp_dir.cleanup()

    def test_summary_aggregates_before_pagination(self):
        result = self.core.search_orders(customer="TrendCart", limit=1)
        self.assertEqual(result["result_status"], "OK")
        self.assertEqual(result["data"]["match_count"], 2)
        self.assertEqual(result["data"]["matched_total_pieces"], 1100)
        self.assertEqual(result["data"]["pagination"]["returned_count"], 1)
        self.assertTrue(result["data"]["pagination"]["has_more"])

    def test_feasibility_accepts_plural_product_names(self):
        for product, category in (("Hoodies", "TOPS"), ("scarves", "ACCESSORIES"), ("beanies", "ACCESSORIES")):
            result = self.core.estimate_order_feasibility(product, category, 100, "2026-04-30")
            self.assertEqual(result["result_status"], "OK", product)
        unknown = self.core.estimate_order_feasibility("Gloves", "ACCESSORIES", 100, "2026-04-30")
        self.assertEqual(unknown["result_status"], "INVALID_INPUT")
        self.assertIn("Supported products", unknown["error"]["message"])

    def _future(self, **delta):
        from datetime import datetime, timedelta, timezone
        return (datetime.now(timezone.utc) + timedelta(**delta)).isoformat()

    def test_reminder_create_list_edit_and_close(self):
        created = self.core.create_reminder("ord-101", "Check knitting progress", self._future(days=3))
        self.assertEqual(created["status"], "CREATED")
        reminder = created["reminder"]
        self.assertEqual(reminder["order_id"], "ORD-101")
        self.assertEqual(reminder["due_state"], "UPCOMING")
        self.assertEqual([r["reminder_id"] for r in self.core.list_reminders()], [reminder["reminder_id"]])
        self.assertEqual(self.core.action_audit()[-1]["status"], "CONFIRMED")  # web creation is logged

        soon = self.core.update_reminder(reminder["reminder_id"], {"note": "Call the line lead", "remind_at": self._future(hours=2)})
        self.assertEqual(soon["reminder"]["note"], "Call the line lead")
        self.assertEqual(soon["reminder"]["due_state"], "DUE_SOON")

        done = self.core.update_reminder(reminder["reminder_id"], {"status": "DONE"})
        self.assertEqual(done["reminder"]["status"], "DONE")
        self.assertEqual(self.core.list_reminders(), [])
        self.assertEqual(len(self.core.list_reminders(include_closed=True)), 1)
        locked = self.core.update_reminder(reminder["reminder_id"], {"note": "edit after done"})
        self.assertEqual(locked["status"], "REFUSED")

    def test_reminder_validation(self):
        self.assertEqual(self.core.create_reminder("ORD-999", "x", self._future(days=1))["error"]["code"], "TARGET_NOT_RESOLVED")
        self.assertEqual(self.core.create_reminder("ORD-101", "x", self._future(days=-1))["status"], "REFUSED")
        self.assertEqual(self.core.create_reminder("ORD-101", "x", "2030-01-01T09:00")["status"], "REFUSED")  # no timezone
        self.assertEqual(self.core.create_reminder("ORD-101", " ", self._future(days=1))["status"], "REFUSED")

    def test_prepared_reminder_is_saved_only_on_confirm(self):
        payload = {"remind_at": self._future(days=2), "message": "Check ORD-101 before 2030-01-05"}
        cancelled = self.core.manage_action("PREPARE", "assistant", "create_reminder", "ORD-101", payload)
        self.assertEqual(cancelled["status"], "PREPARED")  # order IDs and dates do not need claims
        self.core.manage_action("CANCEL", "user", confirmation_token=cancelled["confirmation_token"])
        self.assertEqual(self.core.list_reminders(), [])

        prepared = self.core.manage_action("PREPARE", "assistant", "create_reminder", "ORD-101", payload)
        self.assertEqual(self.core.list_reminders(), [])
        confirmed = self.core.manage_action("CONFIRM", "user", confirmation_token=prepared["confirmation_token"])
        self.assertEqual(confirmed["recorded_effect"]["mode"], "reminder_saved")
        reminders = self.core.list_reminders()
        self.assertEqual(len(reminders), 1)
        self.assertEqual(reminders[0]["action_token"], prepared["confirmation_token"])
        again = self.core.manage_action("CONFIRM", "user", confirmation_token=prepared["confirmation_token"])
        self.assertEqual(again["status"], "REFUSED")
        self.assertEqual(len(self.core.list_reminders()), 1)

    def test_business_numbers_in_actions_still_need_claims(self):
        refused = self.core.manage_action("PREPARE", "assistant", "draft_chase_up_message", "ORD-101",
                                          {"message": "Your 800 pieces are 3 days late."})
        self.assertEqual(refused["error"]["code"], "CLAIM_REQUIRED")

    def test_completed_order_reports_no_inactivity(self):
        completed = next(o for o in self.core.search_orders(status="COMPLETE")["data"]["orders"])
        risk = self.core.assess_order_risk(completed["order_id"])["data"]
        self.assertEqual(risk["risk_level"], "LOW")
        self.assertIsNone(risk["inactive_working_days"])

    def test_brief_baseline_matches_normality_tool(self):
        brief = self.core.discover_operational_issues()
        drops = [f for f in brief["data"]["findings"] + brief["data"]["observation_findings"]
                 if f["category"] == "stage_output_drop"]
        self.assertTrue(drops)
        for finding in drops:
            stage, day = finding["evidence"]["stage"], finding["evidence"]["target_date"]
            direct = self.core.assess_output_normality(day, stage)["data"]
            self.assertEqual(finding["evidence"]["baseline"], direct["baseline"])
            self.assertEqual(finding["evidence"]["baseline_dates"], direct["baseline_dates"])

    def test_brief_lists_findings_that_did_not_fit(self):
        brief = self.core.discover_operational_issues(max_findings=1)
        data = brief["data"]
        self.assertEqual(data["overview"]["published_count"], 1)
        self.assertEqual(data["overview"]["not_shown_count"], len(data["not_shown_findings"]))
        self.assertGreaterEqual(data["overview"]["not_shown_count"], 1)
        self.assertIn("not shown", brief["summary"])

    def test_single_intent_returns_ambiguity_not_first_match(self):
        result = self.core.search_orders(customer="TrendCart", intent="SINGLE")
        self.assertEqual(result["result_status"], "NEEDS_CLARIFICATION")
        self.assertTrue(result["requires_clarification"])
        self.assertEqual(len(result["data"]["clarification"]["candidate_order_ids"]), 2)

    def test_unknown_arguments_are_rejected(self):
        result = self.core.search_orders(revenue=100)
        self.assertEqual(result["result_status"], "INVALID_INPUT")
        self.assertEqual(result["error"]["code"], "UNSUPPORTED_ARGUMENT")

    def test_production_average_uses_operating_days(self):
        result = self.core.get_production_output("2026-03-23", "2026-03-29", ["ASSEMBLY"])
        summary = result["data"]["stage_summaries"][0]
        self.assertEqual(result["result_status"], "OK")
        self.assertEqual(summary["total_pieces"], 4800)
        self.assertEqual(summary["observed_days"], 7)
        self.assertEqual(summary["observed_operating_days"], 6)
        self.assertEqual(summary["average_per_operating_day"], 800)
        self.assertEqual(len(result["data"]["daily_output"]), 6)

    def test_missing_production_key_is_not_filled_with_zero(self):
        path = self.data_dir / "production_log.csv"
        with path.open(encoding="utf-8", newline="") as stream:
            rows = list(csv.DictReader(stream))
        rows = [row for row in rows if not (row["date"] == "2026-03-25" and row["stage"] == "ASSEMBLY")]
        with path.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=("date", "stage", "pieces_completed"))
            writer.writeheader()
            writer.writerows(rows)
        result = self.core.get_production_output("2026-03-23", "2026-03-29", ["ASSEMBLY"])
        summary = result["data"]["stage_summaries"][0]
        self.assertEqual(result["result_status"], "PARTIAL_DATA")
        self.assertEqual(len(result["data"]["missing_keys"]), 1)
        self.assertEqual(summary["total_pieces"], 4000)
        self.assertIsNone(summary["average_per_operating_day"])
        self.assertEqual(summary["totals_scope"], "OBSERVED_ONLY")

    def test_recorded_sunday_zero_is_distinct_from_missing_data(self):
        result = self.core.get_production_output("2026-03-29", "2026-03-29", ["PACKING"])
        summary = result["data"]["stage_summaries"][0]
        self.assertEqual(result["result_status"], "OK")
        self.assertEqual(summary["total_pieces"], 0)
        self.assertEqual(summary["average_reason"], "NO_OPERATING_DAYS")
        self.assertEqual(result["data"]["daily_output"], [])

    def test_output_drop_uses_same_weekday_median(self):
        result = self.core.assess_output_normality("2026-03-31", "ASSEMBLY")
        self.assertEqual(result["data"]["status"], "ABNORMAL")
        self.assertEqual(result["data"]["baseline"], 800)
        self.assertEqual(result["data"]["actual_output"], 400)
        self.assertEqual(result["data"]["deviation_fraction"], 0.5)

    def test_sunday_zero_is_scheduled_closure(self):
        result = self.core.assess_output_normality("2026-03-29", "ASSEMBLY")
        self.assertEqual(result["data"]["status"], "CLOSED_DAY")
        self.assertEqual(result["data"]["reason_code"], "SCHEDULED_CLOSURE")

    def test_risk_assessment_is_explainable(self):
        result = self.core.assess_order_risk("ORD-101")
        self.assertEqual(result["data"]["risk_level"], "HIGH")
        self.assertIn("DEADLINE_APPROACHING", result["data"]["rules_triggered"])
        self.assertIn("ORDER_STAGNANT", result["data"]["rules_triggered"])
        self.assertTrue(result["claim_refs"])

    def test_feasibility_estimates_internal_and_workshop_scenarios(self):
        result = self.core.estimate_order_feasibility("Hoodie", "TOPS", 500, "2026-04-30")
        self.assertEqual(result["result_status"], "OK")
        self.assertEqual(result["data"]["classification"], "LIKELY_FEASIBLE")
        self.assertEqual(result["data"]["bottleneck_stage"], "PACKING")
        self.assertEqual(result["data"]["workshop_scenarios"][0]["workshop_id"], "W1")
        self.assertIn("SUSPENDED", result["data"]["excluded_workshops"][0]["reason_codes"])

    def test_discovery_is_bounded_and_traceable(self):
        result = self.core.discover_operational_issues()
        self.assertEqual(result["result_status"], "OK")
        self.assertLessEqual(len(result["data"]["findings"]), 5)
        self.assertTrue(all(finding["claim_id"] for finding in result["data"]["findings"]))
        self.assertTrue(all(0 <= finding["priority"] <= 100 for finding in result["data"]["findings"]))
        run = self.core.conn.execute("SELECT status FROM brief_runs WHERE run_id=?", (result["data"]["run_id"],)).fetchone()
        self.assertEqual(run["status"], "OK")
        customer_finding = next(item for item in result["data"]["findings"] if item["category"] == "customer_risk_cluster")
        traced = self.core.trace_claim(customer_finding["claim_id"], verify=True)
        self.assertEqual(traced["status"], "OK")
        self.assertEqual(traced["verification"]["result"], "CONSISTENT")

    def test_claim_recomputes_against_same_snapshot(self):
        result = self.core.assess_output_normality("2026-03-31", "ASSEMBLY")
        claim_id = result["claim_refs"][0]["claim_id"]
        traced = self.core.trace_claim(claim_id, verify=True)
        self.assertEqual(traced["status"], "OK")
        self.assertEqual(traced["verification"]["result"], "CONSISTENT")
        self.assertTrue(traced["source_rows"])

    def test_changed_source_marks_claim_stale(self):
        result = self.core.assess_output_normality("2026-03-31", "ASSEMBLY")
        claim_id = result["claim_refs"][0]["claim_id"]
        path = self.data_dir / "production_log.csv"
        text = path.read_text(encoding="utf-8")
        path.write_text(text.replace("2026-03-31,ASSEMBLY,400", "2026-03-31,ASSEMBLY,401"), encoding="utf-8")
        traced = self.core.trace_claim(claim_id, verify=True)
        self.assertEqual(traced["status"], "STALE")
        self.assertEqual(traced["verification"]["result"], "DRIFTED")

    def test_brief_claim_ignores_volatile_run_timestamps(self):
        result = self.core.discover_operational_issues()
        claim_id = result["claim_refs"][0]["claim_id"]
        traced = self.core.trace_claim(claim_id, verify=True)
        self.assertEqual(traced["status"], "OK")
        self.assertEqual(traced["verification"]["result"], "CONSISTENT")

    def test_actions_require_claims_and_confirmation_token(self):
        refusal = self.core.manage_action("PREPARE", "manager", "add_order_note", "ORD-101", {"note": "Call at 9"})
        self.assertEqual(refusal["status"], "REFUSED")
        claim = self.core.search_orders(order_id="ORD-101") ["claim_refs"][0]["claim_id"]
        prepared = self.core.manage_action("PREPARE", "manager", "add_order_note", "ORD-101", {"note": "Call at 9"}, [claim])
        self.assertEqual(prepared["status"], "PREPARED")
        self.assertFalse(prepared["side_effect_executed"])
        confirmed = self.core.manage_action("CONFIRM", "manager", confirmation_token=prepared["confirmation_token"])
        self.assertEqual(confirmed["status"], "CONFIRMED")
        self.assertFalse(confirmed["recorded_effect"]["external_message_sent"])
        audit = self.core.action_audit()[0]
        self.assertEqual(audit["confirmation_token"], prepared["confirmation_token"])
        self.assertEqual(audit["status"], "CONFIRMED")
        self.assertIsNotNone(audit["recorded_effect"])
        replay = self.core.manage_action("CONFIRM", "manager", confirmation_token=prepared["confirmation_token"])
        self.assertEqual(replay["status"], "REFUSED")

    def test_cancel_discards_prepared_action(self):
        claim = self.core.search_orders(order_id="ORD-101")["claim_refs"][0]["claim_id"]
        prepared = self.core.manage_action("PREPARE", "manager", "add_order_note", "ORD-101", {"note": "Check stage"}, [claim])
        cancelled = self.core.manage_action("CANCEL", "manager", confirmation_token=prepared["confirmation_token"])
        self.assertEqual(cancelled["status"], "CANCELLED")
        self.assertFalse(cancelled["side_effect_executed"])

    def test_cli_accepts_payload_file(self):
        payload_path = self.root / "action-payload.json"
        payload_path.write_text(json.dumps({"note": "Check current stage"}), encoding="utf-8")
        result = subprocess.run(
            [sys.executable, str(BACKEND / "copilot.py"), "--data-dir", str(self.data_dir), "--config", str(BACKEND / "rules_config.json"), "--db", ":memory:",
             "action", "PREPARE", "--type", "add_order_note", "--target", "ORD-101", "--payload-file", str(payload_path)],
            capture_output=True, text=True, check=True,
        )
        self.assertEqual(json.loads(result.stdout)["status"], "PREPARED")

    def test_demo_cli_defaults_work_outside_project_directory(self):
        result = subprocess.run(
            [sys.executable, str(BACKEND / "copilot.py"), "--db", str(self.root / "demo.sqlite3"), "demo"],
            cwd=self.root,
            capture_output=True,
            text=True,
            check=True,
        )
        self.assertEqual(json.loads(result.stdout)["mode"], "SYNTHETIC_DEMO_ONLY")


if __name__ == "__main__":
    unittest.main()