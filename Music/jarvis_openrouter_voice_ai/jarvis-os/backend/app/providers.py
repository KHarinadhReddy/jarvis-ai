from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Protocol

import httpx

from .config import Settings, get_settings

log = logging.getLogger("jarvis.provider")


class ProviderError(RuntimeError):
    def __init__(self, message: str, status_code: int = 502) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass
class ChatMessage:
    role: str
    content: Any = None
    tool_calls: list[dict[str, Any]] | None = None
    tool_call_id: str | None = None
    reasoning_content: str | None = None
    name: str | None = None

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"role": self.role}
        if self.content is not None:
            payload["content"] = self.content
        if self.tool_calls:
            payload["tool_calls"] = self.tool_calls
        if self.tool_call_id:
            payload["tool_call_id"] = self.tool_call_id
        if self.reasoning_content:
            payload["reasoning_content"] = self.reasoning_content
        if self.name:
            payload["name"] = self.name
        return payload


class AIProvider(Protocol):
    name: str
    model: str

    async def stream_chat(
        self,
        messages: list[ChatMessage],
        *,
        thinking: bool = False,
        model: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int = 2048,
    ) -> AsyncIterator[dict[str, Any]]: ...

    async def complete(
        self,
        messages: list[ChatMessage],
        *,
        thinking: bool = False,
        model: str | None = None,
        json_mode: bool = False,
        max_tokens: int = 1600,
    ) -> str: ...


class OpenAICompatibleProvider:
    """DeepSeek and OpenRouter both expose the OpenAI chat-completions shape."""

    def __init__(
        self,
        *,
        name: str,
        base_url: str,
        api_key: str,
        model: str,
        supports_thinking: bool = False,
        supports_reasoning: bool = False,
    ) -> None:
        self.name = name
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.supports_thinking = supports_thinking
        self.supports_reasoning = supports_reasoning

    def _headers(self) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        if self.name == "openrouter":
            headers["HTTP-Referer"] = "https://jarvis.local"
            headers["X-Title"] = "J.A.R.V.I.S. Mobile"
        return headers

    def _payload(
        self,
        messages: list[ChatMessage],
        *,
        stream: bool,
        thinking: bool,
        model: str | None,
        tools: list[dict[str, Any]] | None,
        json_mode: bool,
        max_tokens: int,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": model or self.model,
            "messages": [m.to_payload() for m in messages],
            "stream": stream,
            "max_tokens": max_tokens,
        }
        if tools:
            payload["tools"] = tools
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        if self.supports_thinking:
            payload["thinking"] = {"type": "enabled" if thinking else "disabled"}
            if thinking:
                payload["reasoning_effort"] = "high"
        elif self.supports_reasoning and thinking:
            # OpenRouter's normalized reasoning control. Only sent when the user
            # asks for deep reasoning so normal replies stay fast.
            payload["reasoning"] = {"effort": "high"}
        return payload

    async def stream_chat(
        self,
        messages: list[ChatMessage],
        *,
        thinking: bool = False,
        model: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int = 2048,
    ) -> AsyncIterator[dict[str, Any]]:
        if not self.api_key:
            raise ProviderError("AI provider is not configured", 503)
        payload = self._payload(
            messages,
            stream=True,
            thinking=thinking,
            model=model,
            tools=tools,
            json_mode=False,
            max_tokens=max_tokens,
        )
        url = f"{self.base_url}/chat/completions"
        tool_calls: dict[int, dict[str, Any]] = {}
        usage: dict[str, Any] | None = None
        try:
            timeout = httpx.Timeout(connect=15.0, read=120.0, write=30.0, pool=15.0)
            async with httpx.AsyncClient(timeout=timeout) as client:
                async with client.stream("POST", url, headers=self._headers(), json=payload) as response:
                    if response.status_code >= 400:
                        body = (await response.aread()).decode("utf-8", "replace")[:800]
                        raise ProviderError(
                            f"Provider returned HTTP {response.status_code}: {body}",
                            502,
                        )
                    async for line in response.aiter_lines():
                        if not line or not line.startswith("data:"):
                            continue
                        raw = line[5:].strip()
                        if raw == "[DONE]":
                            break
                        try:
                            obj = json.loads(raw)
                        except json.JSONDecodeError:
                            continue
                        if obj.get("usage"):
                            usage = obj["usage"]
                        for choice in obj.get("choices", []):
                            delta = choice.get("delta") or {}
                            reasoning = delta.get("reasoning_content")
                            if reasoning:
                                yield {"type": "reasoning", "text": reasoning}
                            content = delta.get("content")
                            if content:
                                yield {"type": "token", "text": content}
                            for tc in delta.get("tool_calls") or []:
                                index = int(tc.get("index", 0))
                                slot = tool_calls.setdefault(
                                    index,
                                    {"id": "", "type": "function", "function": {"name": "", "arguments": ""}},
                                )
                                if tc.get("id"):
                                    slot["id"] = tc["id"]
                                fn = tc.get("function") or {}
                                if fn.get("name"):
                                    slot["function"]["name"] += fn["name"]
                                if fn.get("arguments"):
                                    slot["function"]["arguments"] += fn["arguments"]
            for slot in tool_calls.values():
                yield {"type": "tool_call", "tool_call": slot}
            if usage:
                yield {"type": "usage", "usage": usage}
            yield {"type": "done"}
        except httpx.TimeoutException as exc:
            raise ProviderError("AI provider timed out", 504) from exc
        except httpx.HTTPError as exc:
            raise ProviderError(f"AI provider network error: {type(exc).__name__}", 502) from exc

    async def complete(
        self,
        messages: list[ChatMessage],
        *,
        thinking: bool = False,
        model: str | None = None,
        json_mode: bool = False,
        max_tokens: int = 1600,
    ) -> str:
        if not self.api_key:
            raise ProviderError("AI provider is not configured", 503)
        payload = self._payload(
            messages,
            stream=False,
            thinking=thinking,
            model=model,
            tools=None,
            json_mode=json_mode,
            max_tokens=max_tokens,
        )
        url = f"{self.base_url}/chat/completions"
        try:
            timeout = httpx.Timeout(connect=15.0, read=120.0, write=30.0, pool=15.0)
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(url, headers=self._headers(), json=payload)
            if response.status_code >= 400:
                body = response.text[:800]
                raise ProviderError(f"Provider returned HTTP {response.status_code}: {body}", 502)
            data = response.json()
            return data["choices"][0]["message"].get("content") or ""
        except httpx.TimeoutException as exc:
            raise ProviderError("AI provider timed out", 504) from exc
        except httpx.HTTPError as exc:
            raise ProviderError(f"AI provider network error: {type(exc).__name__}", 502) from exc


class UnconfiguredProvider:
    name = "unconfigured"
    model = ""

    async def stream_chat(self, *args: Any, **kwargs: Any) -> AsyncIterator[dict[str, Any]]:
        raise ProviderError("No AI key configured. Add DEEPSEEK_API_KEY or OPENROUTER_API_KEY.", 503)
        yield  # pragma: no cover

    async def complete(self, *args: Any, **kwargs: Any) -> str:
        raise ProviderError("No AI key configured. Add DEEPSEEK_API_KEY or OPENROUTER_API_KEY.", 503)


class MockProvider:
    name = "mock"
    model = "mock-jarvis"

    async def stream_chat(
        self,
        messages: list[ChatMessage],
        *,
        thinking: bool = False,
        model: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int = 2048,
    ) -> AsyncIterator[dict[str, Any]]:
        text = "Systems online. This is a test response from the mock provider."
        for token in text.split(" "):
            yield {"type": "token", "text": token + " "}
        yield {"type": "done"}

    async def complete(
        self,
        messages: list[ChatMessage],
        *,
        thinking: bool = False,
        model: str | None = None,
        json_mode: bool = False,
        max_tokens: int = 1600,
    ) -> str:
        if json_mode:
            return '{"description":"A test image.","objects":[],"text":"","translation":"","answer":"Test result","safety":"ok"}'
        return "Systems online. This is a test response from the mock provider."


def build_provider(settings: Settings | None = None) -> AIProvider:
    settings = settings or get_settings()
    if settings.deepseek_api_key:
        return OpenAICompatibleProvider(
            name="deepseek",
            base_url=settings.deepseek_base_url,
            api_key=settings.deepseek_api_key,
            model=settings.deepseek_model,
            supports_thinking=True,
        )
    if settings.openrouter_api_key:
        return OpenAICompatibleProvider(
            name="openrouter",
            base_url=settings.openrouter_base_url,
            api_key=settings.openrouter_api_key,
            model=settings.openrouter_model,
            supports_thinking=False,
            supports_reasoning=True,
        )
    if settings.allow_mock:
        return MockProvider()
    return UnconfiguredProvider()
