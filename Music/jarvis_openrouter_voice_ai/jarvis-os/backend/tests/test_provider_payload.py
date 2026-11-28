from __future__ import annotations

from app.providers import ChatMessage, OpenAICompatibleProvider


def _messages() -> list[ChatMessage]:
    return [ChatMessage(role="user", content="hello")]


def test_openrouter_reasoning_is_only_sent_when_requested():
    provider = OpenAICompatibleProvider(
        name="openrouter",
        base_url="https://example.invalid",
        api_key="test",
        model="deepseek/deepseek-v4.1-flash",
        supports_reasoning=True,
    )
    deep = provider._payload(
        _messages(),
        stream=True,
        thinking=True,
        model=None,
        tools=None,
        json_mode=False,
        max_tokens=100,
    )
    assert deep["reasoning"] == {"effort": "high"}
    assert "thinking" not in deep

    normal = provider._payload(
        _messages(),
        stream=True,
        thinking=False,
        model=None,
        tools=None,
        json_mode=False,
        max_tokens=100,
    )
    assert "reasoning" not in normal


def test_deepseek_official_thinking_payload():
    provider = OpenAICompatibleProvider(
        name="deepseek",
        base_url="https://api.deepseek.com",
        api_key="test",
        model="deepseek-flash",
        supports_thinking=True,
    )
    payload = provider._payload(
        _messages(),
        stream=True,
        thinking=True,
        model=None,
        tools=None,
        json_mode=False,
        max_tokens=100,
    )
    assert payload["thinking"] == {"type": "enabled"}
    assert payload["reasoning_effort"] == "high"
