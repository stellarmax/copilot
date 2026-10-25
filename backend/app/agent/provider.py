"""OpenAI-compatible chat-completions adapter with bounded timeouts."""

from __future__ import annotations

import json
from typing import Any

import httpx


class ModelProviderError(RuntimeError):
    """A safe, user-displayable model provider failure."""


PROVIDER_CATALOG: dict[str, dict[str, Any]] = {
    "chatgpt": {
        "label": "ChatGPT (OpenAI)",
        "base_url": "https://api.openai.com/v1",
        "protocol": "openai",
        "models": [
            {"id": "gpt-4.1-mini", "label": "GPT-4.1 mini"},
            {"id": "gpt-4.1", "label": "GPT-4.1"},
            # Reasoning model: Chat Completions only allows tool calling with reasoning_effort=none,
            # and it rejects temperature/max_tokens.
            {"id": "gpt-6-luna", "label": "GPT-6 Luna", "reasoning": True},
        ],
    },
    "claude": {
        "label": "Claude (Anthropic)",
        "base_url": "https://api.anthropic.com/v1",
        "protocol": "anthropic",
        "models": [
            {"id": "claude-sonnet-5-5", "label": "Claude Sonnet 5.5"},
            {"id": "claude-opus-5-5", "label": "Claude Opus 5.5"},
            {"id": "claude-haiku-4-5-20251001", "label": "Claude Haiku 4.5"},
        ],
    },
    "gemini": {
        "label": "Gemini (Google)",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "protocol": "openai",
        "models": [
            {"id": "gemini-3.8-flash", "label": "Gemini 3.8 Flash"},
            {"id": "gemini-3.5-flash-lite", "label": "Gemini 3.5 Flash-Lite"},
            {"id": "gemini-3.1-pro-preview", "label": "Gemini 3.1 Pro (Preview)"},
        ],
    },
    "deepseek": {
        "label": "DeepSeek",
        "base_url": "https://api.deepseek.com",
        "protocol": "openai",
        "models": [
            {"id": "deepseek-flash", "label": "DeepSeek V4.1 Flash"},
            {"id": "deepseek-v4-pro", "label": "DeepSeek V4 Pro"},
        ],
    },
}


def _model_config(provider: str, model: str) -> dict[str, Any]:
    config = PROVIDER_CATALOG.get(provider, {})
    return next((item for item in config.get("models", []) if item["id"] == model), {})


class OpenAICompatibleProvider:
    def __init__(self, base_url: str, model: str, api_key: str, reasoning: bool = False) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.reasoning = reasoning

    async def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        force_answer: bool = False,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"model": self.model, "messages": messages}
        if self.reasoning:
            body["max_completion_tokens"] = 1200
            body["reasoning_effort"] = "none"
        else:
            body["temperature"] = 0.1
            body["max_tokens"] = 1200
        if tools:
            body["tools"] = tools
            body["tool_choice"] = "none" if force_answer else "auto"
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(35.0), follow_redirects=False) as client:
                response = await client.post(
                    f"{self.base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json=body,
                )
        except httpx.TimeoutException as exc:
            raise ModelProviderError("The AI provider timed out. Please try again.") from exc
        except httpx.HTTPError as exc:
            raise ModelProviderError("Could not connect to the configured AI provider.") from exc

        if response.is_error:
            if response.status_code in (401, 403):
                message = "The AI provider rejected the configured API key. Check it in AI settings."
            elif response.status_code == 429:
                message = "The AI provider rate limit was reached. Please try again shortly."
            else:
                message = f"The AI provider returned HTTP {response.status_code}."
            raise ModelProviderError(message)

        try:
            payload = response.json()
            choice = payload["choices"][0]
            message = choice["message"]
            content = message.get("content")
            if isinstance(content, list):
                content = "".join(
                    item.get("text", "") for item in content if isinstance(item, dict)
                )
            tool_calls = message.get("tool_calls") or []
            if not isinstance(content, (str, type(None))) or not isinstance(tool_calls, list):
                raise TypeError
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise ModelProviderError("The AI provider returned an unsupported response format.") from exc
        return {"content": content or "", "tool_calls": tool_calls}

    async def test_connection(self) -> None:
        result = await self.complete(
            [
                {"role": "system", "content": "Reply with the single word OK."},
                {"role": "user", "content": "Connection test."},
            ]
        )
        if not result["content"]:
            raise ModelProviderError("The AI provider connected but returned no text.")


class AnthropicProvider:
    def __init__(self, base_url: str, model: str, api_key: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key

    def _convert_messages(
        self, messages: list[dict[str, Any]]
    ) -> tuple[str, list[dict[str, Any]]]:
        system_parts: list[str] = []
        converted: list[dict[str, Any]] = []
        for message in messages:
            role = message.get("role")
            if role == "system":
                system_parts.append(str(message.get("content", "")))
            elif role == "tool":
                converted.append({
                    "role": "user",
                    "content": [{
                        "type": "tool_result",
                        "tool_use_id": message["tool_call_id"],
                        "content": message.get("content", ""),
                    }],
                })
            elif role == "assistant" and message.get("tool_calls"):
                blocks: list[dict[str, Any]] = []
                if message.get("content"):
                    blocks.append({"type": "text", "text": message["content"]})
                for call in message["tool_calls"]:
                    function = call.get("function", {})
                    try:
                        arguments = json.loads(function.get("arguments", "{}"))
                    except json.JSONDecodeError:
                        arguments = {}
                    blocks.append({
                        "type": "tool_use",
                        "id": call.get("id", "tool-call"),
                        "name": function.get("name", ""),
                        "input": arguments,
                    })
                converted.append({"role": "assistant", "content": blocks})
            elif role in ("user", "assistant"):
                converted.append({"role": role, "content": message.get("content", "") or ""})
        return "\n\n".join(system_parts), converted

    async def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        force_answer: bool = False,
    ) -> dict[str, Any]:
        system, converted = self._convert_messages(messages)
        body: dict[str, Any] = {
            "model": self.model,
            "max_tokens": 1200,
            "messages": converted,
        }
        if system:
            body["system"] = system
        if tools:
            body["tools"] = [
                {
                    "name": item["function"]["name"],
                    "description": item["function"]["description"],
                    "input_schema": item["function"]["parameters"],
                }
                for item in tools
            ]
            if force_answer:
                body["tool_choice"] = {"type": "none"}
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(35.0), follow_redirects=False) as client:
                response = await client.post(
                    f"{self.base_url}/messages",
                    headers={
                        "x-api-key": self.api_key,
                        "anthropic-version": "2023-06-01",
                    },
                    json=body,
                )
        except httpx.TimeoutException as exc:
            raise ModelProviderError("The AI provider timed out. Please try again.") from exc
        except httpx.HTTPError as exc:
            raise ModelProviderError("Could not connect to the configured AI provider.") from exc

        if response.is_error:
            if response.status_code in (401, 403):
                message = "The AI provider rejected the configured API key. Check it in AI settings."
            elif response.status_code == 429:
                message = "The AI provider rate limit was reached. Please try again shortly."
            else:
                message = f"The AI provider returned HTTP {response.status_code}."
            raise ModelProviderError(message)

        try:
            payload = response.json()
            blocks = payload["content"]
            content = "".join(block.get("text", "") for block in blocks if block.get("type") == "text")
            calls = [block for block in blocks if block.get("type") == "tool_use"]
            tool_calls = [
                {
                    "id": block["id"],
                    "type": "function",
                    "function": {
                        "name": block["name"],
                        "arguments": json.dumps(block.get("input", {}), ensure_ascii=False),
                    },
                }
                for block in calls
            ]
        except (KeyError, TypeError, ValueError) as exc:
            raise ModelProviderError("The AI provider returned an unsupported response format.") from exc
        return {"content": content, "tool_calls": tool_calls}

    async def test_connection(self) -> None:
        result = await self.complete([
            {"role": "system", "content": "Reply with the single word OK."},
            {"role": "user", "content": "Connection test."},
        ])
        if not result["content"]:
            raise ModelProviderError("The AI provider connected but returned no text.")


def create_provider(provider: str, model: str, api_key: str) -> OpenAICompatibleProvider | AnthropicProvider:
    config = PROVIDER_CATALOG.get(provider)
    if config is None:
        raise ModelProviderError("The configured AI provider is not supported.")
    if config["protocol"] == "anthropic":
        return AnthropicProvider(config["base_url"], model, api_key)
    return OpenAICompatibleProvider(
        config["base_url"], model, api_key, reasoning=bool(_model_config(provider, model).get("reasoning"))
    )