import unittest
import json
from unittest.mock import patch

import httpx

from backend.app.agent.provider import (
    PROVIDER_CATALOG,
    ModelProviderError,
    OpenAICompatibleProvider,
    create_provider,
)


class ProviderAdapterTests(unittest.IsolatedAsyncioTestCase):
    async def test_openai_compatible_request_uses_configured_model_and_key(self):
        captured = {}
        real_async_client = httpx.AsyncClient

        async def handler(request):
            captured["url"] = str(request.url)
            captured["authorization"] = request.headers.get("authorization")
            captured["body"] = request.read().decode("utf-8")
            return httpx.Response(
                200,
                json={"choices": [{"message": {"content": "OK", "tool_calls": []}}]},
                request=request,
            )

        transport = httpx.MockTransport(handler)

        def client_factory(**kwargs):
            return real_async_client(transport=transport, **kwargs)

        provider = OpenAICompatibleProvider(
            "https://api.example.test/v1/", "test-model", "provider-secret"
        )
        with patch("backend.app.agent.provider.httpx.AsyncClient", side_effect=client_factory):
            response = await provider.complete([{"role": "user", "content": "hello"}])

        self.assertEqual(response["content"], "OK")
        self.assertEqual(captured["url"], "https://api.example.test/v1/chat/completions")
        self.assertEqual(captured["authorization"], "Bearer provider-secret")
        self.assertEqual(json.loads(captured["body"])["model"], "test-model")

    async def test_invalid_provider_key_is_reported_without_echoing_secret(self):
        async def handler(request):
            return httpx.Response(401, json={"error": "provider-secret rejected"}, request=request)

        real_async_client = httpx.AsyncClient
        transport = httpx.MockTransport(handler)

        def client_factory(**kwargs):
            return real_async_client(transport=transport, **kwargs)

        provider = OpenAICompatibleProvider(
            "https://api.example.test/v1", "test-model", "provider-secret"
        )
        with patch("backend.app.agent.provider.httpx.AsyncClient", side_effect=client_factory):
            with self.assertRaises(ModelProviderError) as raised:
                await provider.complete([{"role": "user", "content": "hello"}])

        self.assertIn("rejected", str(raised.exception))
        self.assertNotIn("provider-secret", str(raised.exception))

    async def test_reasoning_model_uses_completion_token_limit_without_temperature(self):
        captured = {}
        real_async_client = httpx.AsyncClient

        async def handler(request):
            captured["body"] = json.loads(request.read().decode("utf-8"))
            return httpx.Response(
                200,
                json={"choices": [{"message": {"content": "OK", "tool_calls": []}}]},
                request=request,
            )

        transport = httpx.MockTransport(handler)

        def client_factory(**kwargs):
            return real_async_client(transport=transport, **kwargs)

        provider = create_provider("chatgpt", "gpt-6-luna", "provider-secret")
        with patch("backend.app.agent.provider.httpx.AsyncClient", side_effect=client_factory):
            await provider.complete([{"role": "user", "content": "hello"}])

        self.assertEqual(captured["body"]["max_completion_tokens"], 1200)
        self.assertEqual(captured["body"]["reasoning_effort"], "none")
        self.assertNotIn("temperature", captured["body"])
        self.assertNotIn("max_tokens", captured["body"])

    async def test_force_answer_disables_tool_choice_for_both_protocols(self):
        captured = []
        real_async_client = httpx.AsyncClient

        async def handler(request):
            captured.append(json.loads(request.read().decode("utf-8")))
            if request.url.path.endswith("/messages"):
                payload = {"content": [{"type": "text", "text": "OK"}]}
            else:
                payload = {"choices": [{"message": {"content": "OK", "tool_calls": []}}]}
            return httpx.Response(200, json=payload, request=request)

        transport = httpx.MockTransport(handler)

        def client_factory(**kwargs):
            return real_async_client(transport=transport, **kwargs)

        tools = [{
            "type": "function",
            "function": {"name": "noop", "description": "No-op.", "parameters": {"type": "object", "properties": {}}},
        }]
        messages = [{"role": "user", "content": "hello"}]
        with patch("backend.app.agent.provider.httpx.AsyncClient", side_effect=client_factory):
            await create_provider("chatgpt", "gpt-4.1-mini", "k").complete(messages, tools, force_answer=True)
            await create_provider("claude", "claude-sonnet-5-5", "k").complete(messages, tools, force_answer=True)

        self.assertEqual(captured[0]["tool_choice"], "none")
        self.assertEqual(captured[1]["tool_choice"], {"type": "none"})

    def test_catalog_models_are_unique_per_provider(self):
        for provider_id, config in PROVIDER_CATALOG.items():
            ids = [item["id"] for item in config["models"]]
            self.assertEqual(len(ids), len(set(ids)), provider_id)
            self.assertTrue(config["base_url"].startswith("https://"), provider_id)


if __name__ == "__main__":
    unittest.main()
