import base64
import asyncio
import os
import shutil
import sqlite3
import secrets
import tempfile
import unittest
from pathlib import Path
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch

import httpx

from backend.app.main import create_app


ROOT = Path(__file__).resolve().parent.parent


class BackendApiTests(IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.data_dir = self.root / "data"
        shutil.copytree(ROOT / "demo_data", self.data_dir)
        app = create_app(
            data_dir=self.data_dir,
            db_path=self.root / "api.sqlite3",
            config_path=ROOT / "backend" / "rules_config.json",
        )
        self.app = app
        self.clients = []
        self.client = await self.signed_in_client("manager@example.com")

    async def signed_in_client(self, email, password="correct horse 1"):
        client = httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app), base_url="http://127.0.0.1")
        self.clients.append(client)
        registered = await client.post("/api/v1/auth/register", json={"email": email, "password": password})
        self.assertEqual(registered.status_code, 200, registered.text)
        return client

    async def asyncTearDown(self):
        for client in self.clients:
            await client.aclose()
        self.temp_dir.cleanup()

    async def test_health_search_and_claim_trace(self):
        health = await self.client.get("/health")
        self.assertEqual(health.json(), {"status": "ok"})

        response = await self.client.get(
            "/api/v1/orders",
            params={"customer": "TrendCart", "intent": "SUMMARY"},
        )
        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertEqual(result["data"]["match_count"], 2)
        claim_id = result["claim_refs"][0]["claim_id"]

        traced = await self.client.get(f"/api/v1/claims/{claim_id}")
        self.assertEqual(traced.status_code, 200)
        self.assertEqual(traced.json()["claim_id"], claim_id)
        verified = await self.client.post(f"/api/v1/claims/{claim_id}/verify")
        self.assertEqual(verified.status_code, 200)
        self.assertEqual(verified.json()["verification"]["result"], "CONSISTENT")

    async def test_tool_validation_and_feasibility(self):
        invalid = await self.client.get("/api/v1/orders", params={"limit": 101})
        self.assertEqual(invalid.status_code, 422)
        unsupported = await self.client.get("/api/v1/orders", params={"revenue": 100})
        self.assertEqual(unsupported.status_code, 422)

        response = await self.client.post(
            "/api/v1/feasibility",
            json={
                "product": "Hoodie",
                "category": "TOPS",
                "pieces": 500,
                "requested_due_date": "2026-04-30",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["classification"], "LIKELY_FEASIBLE")

    async def test_production_risk_normality_and_brief_routes(self):
        production = await self.client.get(
            "/api/v1/production",
            params={"start": "2026-03-23", "end": "2026-03-29", "stage": "ASSEMBLY"},
        )
        self.assertEqual(production.status_code, 200)
        self.assertEqual(production.json()["data"]["stage_summaries"][0]["total_pieces"], 4800)

        risk = await self.client.get("/api/v1/orders/ORD-101/risk")
        self.assertEqual(risk.status_code, 200)
        self.assertEqual(risk.json()["data"]["risk_level"], "HIGH")

        normality = await self.client.get(
            "/api/v1/production/normality",
            params={"date": "2026-03-31", "stage": "ASSEMBLY"},
        )
        self.assertEqual(normality.status_code, 200)
        self.assertEqual(normality.json()["data"]["status"], "ABNORMAL")

        brief = await self.client.post("/api/v1/brief", json={})
        self.assertEqual(brief.status_code, 200)
        self.assertIn("findings", brief.json()["data"])

    async def test_parallel_requests_use_request_scoped_sqlite_connections(self):
        orders, production = await asyncio.gather(
            self.client.get("/api/v1/orders", params={"limit": 1}),
            self.client.get(
                "/api/v1/production",
                params={"start": "2026-03-23", "end": "2026-03-29", "stage": "ASSEMBLY"},
            ),
        )
        self.assertEqual(orders.status_code, 200)
        self.assertEqual(production.status_code, 200)

    async def test_action_requires_prepare_then_explicit_confirmation(self):
        query = await self.client.get(
            "/api/v1/orders", params={"order_id": "ORD-101", "intent": "SINGLE"}
        )
        claim_id = query.json()["claim_refs"][0]["claim_id"]
        prepared = await self.client.post(
            "/api/v1/actions",
            json={
                "action_type": "add_order_note",
                "target": "ORD-101",
                "payload": {"note": "Review the current stage"},
                "claim_ids": [claim_id],
            },
        )
        self.assertEqual(prepared.status_code, 200)
        body = prepared.json()
        self.assertEqual(body["status"], "PREPARED")
        self.assertFalse(body["side_effect_executed"])

        confirmed = await self.client.post(
            f"/api/v1/actions/{body['confirmation_token']}/confirm"
        )
        self.assertEqual(confirmed.status_code, 200)
        self.assertFalse(confirmed.json()["recorded_effect"]["external_message_sent"])

        replay = await self.client.post(
            f"/api/v1/actions/{body['confirmation_token']}/confirm"
        )
        self.assertEqual(replay.status_code, 409)

        cancelled_prepare = await self.client.post(
            "/api/v1/actions",
            json={
                "action_type": "add_order_note",
                "target": "ORD-101",
                "payload": {"note": "Cancel this prepared note"},
                "claim_ids": [claim_id],
            },
        )
        cancelled = await self.client.post(
            f"/api/v1/actions/{cancelled_prepare.json()['confirmation_token']}/cancel"
        )
        self.assertEqual(cancelled.status_code, 200)
        self.assertEqual(cancelled.json()["status"], "CANCELLED")

    async def test_ai_settings_encrypts_key_and_never_returns_it(self):
        encoded_key = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode("ascii")
        with patch.dict(os.environ, {"AI_CREDENTIALS_ENCRYPTION_KEY": encoded_key}):
            saved = await self.client.put(
                "/api/v1/settings/ai",
                json={
                    "provider": "chatgpt",
                    "model": "gpt-4.1-mini",
                    "api_key": "sentinel-api-secret",
                },
            )
            self.assertEqual(saved.status_code, 200)
            self.assertTrue(saved.json()["has_api_key"])
            self.assertNotIn("api_key", saved.json())
            self.assertNotIn("sentinel-api-secret", saved.text)

            connection_test = AsyncMock(return_value=None)
            with patch("backend.app.main.AgentService.test_connection", connection_test):
                tested = await self.client.post("/api/v1/settings/ai/test")
            self.assertEqual(tested.status_code, 200)
            connection_test.assert_awaited_once()

            database = sqlite3.connect(self.root / "api.sqlite3")
            ciphertext = database.execute(
                "SELECT api_key_ciphertext FROM user_ai_settings"
            ).fetchone()[0]
            database.close()
            self.assertNotIn(b"sentinel-api-secret", ciphertext)

            settings = await self.client.get("/api/v1/settings/ai")
            self.assertEqual(settings.status_code, 200)
            self.assertTrue(settings.json()["has_api_key"])
            self.assertNotIn("sentinel-api-secret", settings.text)

            deleted = await self.client.delete("/api/v1/settings/ai/credential")
            self.assertEqual(deleted.status_code, 200)
            self.assertFalse(deleted.json()["has_api_key"])

    async def test_api_requires_sign_in(self):
        anonymous = httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app), base_url="http://127.0.0.1")
        self.clients.append(anonymous)
        self.assertEqual((await anonymous.get("/health")).status_code, 200)
        for path in ("/api/v1/orders", "/api/v1/settings/ai", "/api/v1/chat/conversations", "/api/v1/reminders"):
            self.assertEqual((await anonymous.get(path)).status_code, 401, path)
        self.assertEqual((await anonymous.get("/api/v1/auth/me")).status_code, 401)
        self.assertEqual((await self.client.get("/api/v1/auth/me")).json()["email"], "manager@example.com")

    async def test_login_logout_and_bad_passwords(self):
        fresh = httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app), base_url="http://127.0.0.1")
        self.clients.append(fresh)
        wrong = await fresh.post("/api/v1/auth/login", json={"email": "manager@example.com", "password": "nope"})
        self.assertEqual(wrong.status_code, 401)
        ok = await fresh.post("/api/v1/auth/login", json={"email": "MANAGER@example.com ", "password": "correct horse 1"})
        self.assertEqual(ok.status_code, 200)
        cookie = ok.headers["set-cookie"].lower()
        self.assertIn("httponly", cookie)
        self.assertIn("samesite=lax", cookie)
        self.assertEqual((await fresh.get("/api/v1/orders", params={"limit": 1})).status_code, 200)
        await fresh.post("/api/v1/auth/logout")
        self.assertEqual((await fresh.get("/api/v1/orders", params={"limit": 1})).status_code, 401)
        duplicate = await fresh.post("/api/v1/auth/register", json={"email": "manager@example.com", "password": "whatever123"})
        self.assertEqual(duplicate.status_code, 409)

    async def test_display_name_can_be_changed(self):
        changed = await self.client.patch("/api/v1/auth/me", json={"display_name": "  Grace Ma "})
        self.assertEqual(changed.status_code, 200)
        self.assertEqual(changed.json()["display_name"], "Grace Ma")
        self.assertEqual((await self.client.get("/api/v1/auth/me")).json()["display_name"], "Grace Ma")
        self.assertEqual((await self.client.patch("/api/v1/auth/me", json={"display_name": "   "})).status_code, 422)
        self.assertEqual((await self.client.patch("/api/v1/auth/me", json={"display_name": "x" * 61})).status_code, 422)

    async def test_repeated_failures_are_throttled(self):
        fresh = httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app), base_url="http://127.0.0.1")
        self.clients.append(fresh)
        for _ in range(5):
            await fresh.post("/api/v1/auth/login", json={"email": "manager@example.com", "password": "wrong-guess"})
        blocked = await fresh.post("/api/v1/auth/login", json={"email": "manager@example.com", "password": "correct horse 1"})
        self.assertEqual(blocked.status_code, 429)

    async def test_registration_needs_invite_code_unless_local(self):
        tunnel = httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app), base_url="http://copilot.example.com")
        self.clients.append(tunnel)
        body = {"email": "stranger@example.com", "password": "long enough 1"}
        self.assertEqual((await tunnel.post("/api/v1/auth/register", json=body)).status_code, 403)
        with patch.dict(os.environ, {"COPILOT_INVITE_CODE": "team-secret-16"}):
            self.assertEqual((await tunnel.post("/api/v1/auth/register", json={**body, "invite_code": "guess"})).status_code, 403)
            ok = await tunnel.post("/api/v1/auth/register", json={**body, "invite_code": "team-secret-16"})
            self.assertEqual(ok.status_code, 200)

    async def test_each_user_sees_only_their_own_key_chats_and_reminders(self):
        from datetime import datetime, timedelta, timezone

        encoded_key = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode("ascii")
        other = await self.signed_in_client("teammate@example.com")
        with patch.dict(os.environ, {"AI_CREDENTIALS_ENCRYPTION_KEY": encoded_key}):
            await self.client.put("/api/v1/settings/ai", json={"provider": "chatgpt", "model": "gpt-4.1-mini", "api_key": "manager-key"})
            self.assertTrue((await self.client.get("/api/v1/settings/ai")).json()["has_api_key"])
            self.assertFalse((await other.get("/api/v1/settings/ai")).json()["has_api_key"])
        conversation = (await self.client.post("/api/v1/chat/conversations", json={"title": "Private"})).json()
        self.assertEqual((await other.get("/api/v1/chat/conversations")).json(), [])
        self.assertEqual((await other.get(f"/api/v1/chat/conversations/{conversation['conversation_id']}")).status_code, 404)
        when = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
        reminder = (await self.client.post("/api/v1/reminders", json={"order_id": "ORD-101", "note": "Mine", "remind_at": when})).json()
        self.assertEqual((await other.get("/api/v1/reminders")).json(), [])
        stolen = await other.patch(f"/api/v1/reminders/{reminder['reminder']['reminder_id']}", json={"status": "CANCELLED"})
        self.assertEqual(stolen.status_code, 404)
        self.assertEqual((await other.get("/api/v1/actions")).json(), [])
        prepared = (await self.client.post("/api/v1/actions", json={
            "action_type": "add_order_note", "target": "ORD-101", "payload": {"note": "Check the knitting stage"}})).json()
        self.assertEqual((await other.post(f"/api/v1/actions/{prepared['confirmation_token']}/confirm")).status_code, 409)
        self.assertEqual((await self.client.post(f"/api/v1/actions/{prepared['confirmation_token']}/confirm")).status_code, 200)

    async def test_reminder_routes(self):
        from datetime import datetime, timedelta, timezone

        when = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
        created = await self.client.post("/api/v1/reminders", json={"order_id": "ORD-101", "note": "Check stage", "remind_at": when})
        self.assertEqual(created.status_code, 200)
        reminder_id = created.json()["reminder"]["reminder_id"]
        listed = await self.client.get("/api/v1/reminders")
        self.assertEqual([r["reminder_id"] for r in listed.json()], [reminder_id])
        edited = await self.client.patch(f"/api/v1/reminders/{reminder_id}", json={"note": "Check washing"})
        self.assertEqual(edited.json()["reminder"]["note"], "Check washing")
        cancelled = await self.client.patch(f"/api/v1/reminders/{reminder_id}", json={"status": "CANCELLED"})
        self.assertEqual(cancelled.json()["reminder"]["status"], "CANCELLED")
        self.assertEqual((await self.client.get("/api/v1/reminders")).json(), [])
        missing_order = await self.client.post("/api/v1/reminders", json={"order_id": "ORD-999", "note": "x", "remind_at": when})
        self.assertEqual(missing_order.status_code, 404)
        unknown = await self.client.patch("/api/v1/reminders/REM-NOPE", json={"note": "x"})
        self.assertEqual(unknown.status_code, 404)

    async def test_switching_provider_requires_that_providers_key(self):
        encoded_key = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode("ascii")
        with patch.dict(os.environ, {"AI_CREDENTIALS_ENCRYPTION_KEY": encoded_key}):
            saved = await self.client.put(
                "/api/v1/settings/ai",
                json={"provider": "chatgpt", "model": "gpt-4.1-mini", "api_key": "openai-key"},
            )
            self.assertEqual(saved.status_code, 200)
            same_provider = await self.client.put(
                "/api/v1/settings/ai", json={"provider": "chatgpt", "model": "gpt-4.1"}
            )
            self.assertEqual(same_provider.status_code, 200)
            switched_without_key = await self.client.put(
                "/api/v1/settings/ai", json={"provider": "claude", "model": "claude-sonnet-5-5"}
            )
            self.assertEqual(switched_without_key.status_code, 422)
            self.assertEqual((await self.client.get("/api/v1/settings/ai")).json()["provider"], "chatgpt")
            switched_with_key = await self.client.put(
                "/api/v1/settings/ai",
                json={"provider": "claude", "model": "claude-sonnet-5-5", "api_key": "anthropic-key"},
            )
            self.assertEqual(switched_with_key.status_code, 200)

    async def test_ai_settings_rejects_client_base_url_override(self):
        response = await self.client.put(
            "/api/v1/settings/ai",
            json={
                "provider": "chatgpt",
                "model": "gpt-4.1-mini",
                "base_url": "https://attacker.example/v1",
                "api_key": "test-key",
            },
        )
        self.assertEqual(response.status_code, 422)

    async def test_chat_conversation_and_optional_memory_routes(self):
        settings = await self.client.get("/api/v1/settings/chat-memory")
        self.assertEqual(settings.status_code, 200)
        self.assertFalse(settings.json()["enabled"])

        refused = await self.client.post(
            "/api/v1/chat/memories", json={"content": "Prefer concise replies"}
        )
        self.assertEqual(refused.status_code, 409)

        conversation = await self.client.post(
            "/api/v1/chat/conversations", json={"title": "Order review"}
        )
        self.assertEqual(conversation.status_code, 200)
        conversation_id = conversation.json()["conversation_id"]
        stored = await self.client.get(f"/api/v1/chat/conversations/{conversation_id}")
        self.assertEqual(stored.status_code, 200)
        self.assertEqual(stored.json()["messages"], [])

        enabled = await self.client.put(
            "/api/v1/settings/chat-memory", json={"enabled": True}
        )
        self.assertTrue(enabled.json()["enabled"])
        memory = await self.client.post(
            "/api/v1/chat/memories", json={"content": "Prefer concise replies"}
        )
        self.assertEqual(memory.status_code, 200)
        listed = await self.client.get("/api/v1/chat/memories")
        self.assertEqual(len(listed.json()), 1)
        removed = await self.client.delete(
            f"/api/v1/chat/memories/{memory.json()['memory_id']}"
        )
        self.assertTrue(removed.json()["deleted"])


if __name__ == "__main__":
    unittest.main()