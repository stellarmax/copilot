import base64
from concurrent.futures import ThreadPoolExecutor
import json
import os
import secrets
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from httpx import ASGITransport, AsyncClient

from backend.app.agent.service import AgentService
from backend.app.agent.store import AgentStore
from backend.app.main import create_app
from backend.copilot import DEFAULT_CONFIG_PATH, DEFAULT_DEMO_DATA_DIR, CopilotCore


class FakeProvider:
    def __init__(self, tool_name="search_orders", arguments=None):
        self.tool_name = tool_name
        self.arguments = arguments or {"customer": "TrendCart", "intent": "SUMMARY"}
        self.calls = 0
        self.messages = []

    async def complete(self, messages, tools=None, force_answer=False):
        self.messages = messages
        self.calls += 1
        if self.calls == 1:
            return {
                "content": "",
                "tool_calls": [{
                    "id": "call-1",
                    "type": "function",
                    "function": {
                        "name": self.tool_name,
                        "arguments": json.dumps(self.arguments),
                    },
                }],
            }
        tool_messages = [message for message in messages if message.get("role") == "tool"]
        tool_result = json.loads(tool_messages[-1]["content"])
        claim_id = tool_result.get("claim_refs", [{}])[0].get("claim_id", "")
        return {
            "content": f"I found {tool_result.get('data', {}).get('match_count', 0)} matching orders. Claim: {claim_id}",
            "tool_calls": [],
        }


class ToolHungryProvider:
    """Requests tools on every call unless tools are disabled, like an over-eager model."""

    def __init__(self, calls_per_round=1):
        self.calls_per_round = calls_per_round
        self.force_flags = []
        self.messages = []

    async def complete(self, messages, tools=None, force_answer=False):
        self.messages = messages
        self.force_flags.append(force_answer)
        if force_answer:
            results = [message for message in messages if message.get("role") == "tool"]
            return {"content": f"Answer from {len(results)} tool results.", "tool_calls": []}
        round_number = len(self.force_flags)
        return {
            "content": "",
            "tool_calls": [
                {
                    "id": f"call-{round_number}-{index}",
                    "type": "function",
                    "function": {
                        "name": "assess_order_risk",
                        "arguments": json.dumps({"order_id": "ORD-101"}),
                    },
                }
                for index in range(self.calls_per_round)
            ],
        }


class TrimEvidenceTests(unittest.TestCase):
    def test_drops_raw_provenance_but_keeps_finding_details(self):
        from backend.app.agent.tools import trim_evidence

        result = {
            "evidence": {"source_rows": [{"order_id": "ORD-1"}]},
            "data": {"findings": [{"summary": "2 high-risk orders",
                                   "evidence": {"affected_orders": ["ORD-1", "ORD-2"], "_source": {"line": 3}}}]},
        }
        trimmed = trim_evidence(result)
        self.assertNotIn("evidence", trimmed)
        finding_evidence = trimmed["data"]["findings"][0]["evidence"]
        self.assertEqual(finding_evidence["affected_orders"], ["ORD-1", "ORD-2"])
        self.assertNotIn("_source", finding_evidence)


class RelativeDateTests(unittest.TestCase):
    def test_relative_periods_are_spelled_out_from_the_business_date(self):
        from backend.app.agent.service import _relative_dates

        text = _relative_dates("2026-04-01")
        self.assertIn("yesterday: 2026-03-31", text)
        self.assertIn("last week: 2026-03-23 to 2026-03-29", text)
        self.assertIn("last month: 2026-03-01 to 2026-03-31", text)
        self.assertIn("next month: 2026-05-01 to 2026-05-31", text)


class AgentServiceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.db_path = self.root / "agent.sqlite3"
        self.previous_key = os.environ.get("AI_CREDENTIALS_ENCRYPTION_KEY")
        os.environ["AI_CREDENTIALS_ENCRYPTION_KEY"] = base64.urlsafe_b64encode(
            secrets.token_bytes(32)
        ).decode("ascii")
        self.store = AgentStore(self.db_path)
        self.store.save_ai_settings(
            "chatgpt", "https://api.openai.com/v1", "gpt-4.1-mini", "fake-key"
        )
        self.core = CopilotCore(DEFAULT_DEMO_DATA_DIR, self.db_path, DEFAULT_CONFIG_PATH)
        self.conversation = self.store.create_conversation("Order question")

    async def asyncTearDown(self):
        self.core.close()
        self.store.close()
        if self.previous_key is None:
            os.environ.pop("AI_CREDENTIALS_ENCRYPTION_KEY", None)
        else:
            os.environ["AI_CREDENTIALS_ENCRYPTION_KEY"] = self.previous_key
        self.temp_dir.cleanup()

    async def test_read_only_tool_turn_returns_claims_and_persists_messages(self):
        service = AgentService(self.store, self.core)
        provider = FakeProvider()
        service.provider = lambda: provider

        result = await service.run_turn(
            self.conversation["conversation_id"], "How many orders does TrendCart have?"
        )

        self.assertEqual(result["status"], "OK")
        self.assertEqual(result["tool_events"][0]["tool_name"], "search_orders")
        self.assertEqual(result["tool_events"][0]["data"]["match_count"], 2)
        self.assertEqual(len(result["claim_refs"]), 1)
        self.assertIn(result["claim_refs"][0], result["assistant_message"])
        stored = self.store.get_conversation(self.conversation["conversation_id"])
        self.assertEqual([message["role"] for message in stored["messages"]], ["user", "assistant"])
        self.assertEqual(stored["messages"][1]["metadata"]["tool_events"][0]["tool_name"], "search_orders")

    async def test_model_cannot_invoke_action_or_unregistered_tool(self):
        service = AgentService(self.store, self.core)
        provider = FakeProvider(tool_name="manage_action", arguments={"operation": "CONFIRM"})
        service.provider = lambda: provider

        result = await service.run_turn(
            self.conversation["conversation_id"], "Confirm the pending order note."
        )

        self.assertEqual(result["status"], "OK")
        self.assertEqual(result["tool_events"][0]["result_status"], "TOOL_ERROR")
        action_count = self.store.connection.execute("SELECT COUNT(*) FROM action_records").fetchone()[0]
        self.assertEqual(action_count, 0)
        self.assertNotIn("manage_action", [tool["function"]["name"] for tool in __import__("backend.app.agent.tools", fromlist=["OPENAI_TOOLS"]).OPENAI_TOOLS])

    async def test_agent_prepares_reminder_but_cannot_confirm_it(self):
        from datetime import datetime, timedelta, timezone

        when = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()
        service = AgentService(self.store, self.core)
        provider = FakeProvider(tool_name="prepare_action", arguments={
            "action_type": "create_reminder", "order_id": "ORD-101", "text": "Check knitting progress", "remind_at": when})
        service.provider = lambda: provider

        result = await service.run_turn(self.conversation["conversation_id"], "Remind me to check ORD-101 in two days")

        pending = result["pending_actions"]
        self.assertEqual(len(pending), 1)
        token = pending[0]["confirmation_token"]
        self.assertEqual(pending[0]["preview"]["action_type"], "create_reminder")
        self.assertNotIn(token, json.dumps(provider.messages))  # the model never sees the token
        self.assertNotIn(token, json.dumps(result["tool_events"]))
        self.assertEqual(self.core.list_reminders(), [])  # nothing saved before the user confirms
        stored = self.store.get_conversation(self.conversation["conversation_id"])["messages"][-1]
        self.assertEqual(stored["metadata"]["pending_actions"][0]["confirmation_token"], token)

        self.core.manage_action("CONFIRM", "user", confirmation_token=token)
        self.assertEqual(len(self.core.list_reminders()), 1)

    async def test_opt_in_memory_is_added_as_non_evidence_context(self):
        self.store.set_memory_enabled(True)
        self.store.add_memory("Prefer concise answers")
        service = AgentService(self.store, self.core)
        provider = FakeProvider()
        service.provider = lambda: provider

        await service.run_turn(self.conversation["conversation_id"], "Summarize TrendCart orders.")

        system_message = provider.messages[0]["content"]
        self.assertIn("Prefer concise answers", system_message)
        self.assertIn("never evidence for factory facts", system_message)

    async def test_exhausted_tool_rounds_still_produce_an_answer(self):
        service = AgentService(self.store, self.core)
        provider = ToolHungryProvider()
        service.provider = lambda: provider

        result = await service.run_turn(self.conversation["conversation_id"], "Which orders need attention?")

        self.assertEqual(result["status"], "OK")
        self.assertEqual(provider.force_flags, [False, False, False, True])
        self.assertEqual(len(result["tool_events"]), 3)
        self.assertEqual(result["assistant_message"], "Answer from 3 tool results.")

    async def test_tool_call_budget_skips_extra_calls_then_forces_answer(self):
        service = AgentService(self.store, self.core)
        provider = ToolHungryProvider(calls_per_round=7)
        service.provider = lambda: provider

        result = await service.run_turn(self.conversation["conversation_id"], "Check every order.")

        self.assertEqual(result["status"], "OK")
        self.assertEqual(provider.force_flags, [False, True])
        self.assertEqual(len(result["tool_events"]), 5)
        tool_messages = [message for message in provider.messages if message.get("role") == "tool"]
        self.assertEqual(len(tool_messages), 7)
        self.assertIn("budget", json.loads(tool_messages[-1]["content"])["error"])

    async def test_system_prompt_states_business_date(self):
        service = AgentService(self.store, self.core)
        provider = FakeProvider()
        service.provider = lambda: provider

        await service.run_turn(self.conversation["conversation_id"], "How did assembly perform last week?")

        self.assertIn(f"business date is {self.core.as_of_date.isoformat()}", provider.messages[0]["content"])

    async def test_request_store_connection_can_cross_worker_thread(self):
        with ThreadPoolExecutor(max_workers=1) as executor:
            settings = executor.submit(self.store.get_ai_settings).result()
        self.assertEqual(settings["model"], "gpt-4.1-mini")

    async def test_chat_api_runs_a_read_only_tool_turn(self):
        data_dir = self.root / "api-data"
        shutil.copytree(DEFAULT_DEMO_DATA_DIR, data_dir)
        app = create_app(
            data_dir=data_dir,
            db_path=self.root / "chat-api.sqlite3",
            config_path=DEFAULT_CONFIG_PATH,
        )
        transport = ASGITransport(app=app)
        fake_provider = FakeProvider()
        with patch.object(AgentService, "provider", return_value=fake_provider):
            async with AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
                saved = await client.put(
                    "/api/v1/settings/ai",
                    json={
                        "provider": "chatgpt",
                        "model": "gpt-4.1-mini",
                        "api_key": "fake-test-key",
                    },
                )
                self.assertEqual(saved.status_code, 200)
                conversation = await client.post(
                    "/api/v1/chat/conversations", json={"title": "TrendCart"}
                )
                turn = await client.post(
                    f"/api/v1/chat/conversations/{conversation.json()['conversation_id']}/turns",
                    json={"message": "How many orders does TrendCart have?"},
                )
                self.assertEqual(turn.status_code, 200)
                body = turn.json()
                self.assertEqual(body["tool_events"][0]["tool_name"], "search_orders")
                self.assertEqual(body["tool_events"][0]["data"]["match_count"], 2)
                self.assertEqual(len(body["claim_refs"]), 1)
                self.assertIn(body["claim_refs"][0], body["assistant_message"])
                history = await client.get(
                    f"/api/v1/chat/conversations/{conversation.json()['conversation_id']}"
                )
                self.assertEqual([item["role"] for item in history.json()["messages"]], ["user", "assistant"])

    async def test_non_loopback_cannot_access_ai_settings_or_chat(self):
        data_dir = self.root / "remote-api-data"
        shutil.copytree(DEFAULT_DEMO_DATA_DIR, data_dir)
        app = create_app(
            data_dir=data_dir,
            db_path=self.root / "remote-api.sqlite3",
            config_path=DEFAULT_CONFIG_PATH,
        )
        transport = ASGITransport(app=app, client=("192.0.2.25", 50000))
        async with AsyncClient(transport=transport, base_url="http://example.test") as client:
            settings = await client.get("/api/v1/settings/ai")
            conversations = await client.get("/api/v1/chat/conversations")
        self.assertEqual(settings.status_code, 403)
        self.assertEqual(conversations.status_code, 403)


if __name__ == "__main__":
    unittest.main()
