from __future__ import annotations

import io
import os

os.environ.setdefault("DEVICE_TOKEN", "jarvis-dev-token")
os.environ.setdefault("ALLOW_MOCK", "1")
os.environ.setdefault("DEEPSEEK_API_KEY", "")
os.environ.setdefault("OPENROUTER_API_KEY", "")

from fastapi.testclient import TestClient

from app.deps import get_provider
from app.main import app
from app.providers import MockProvider

app.dependency_overrides[get_provider] = lambda: MockProvider()
client = TestClient(app)
AUTH = {"Authorization": "Bearer jarvis-dev-token"}


def test_health_is_public():
    response = client.get("/v1/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "online"
    assert body["tts"] == "edge-neural"


def test_models_returns_more_than_three_models():
    response = client.get("/v1/models")
    assert response.status_code == 200
    body = response.json()
    models = body.get("models") or []
    assert isinstance(models, list)
    assert len(models) > 3
    assert body["default"]


def test_chat_requires_token():
    response = client.post("/v1/chat/stream", json={"messages": [{"role": "user", "content": "hi"}]})
    assert response.status_code == 401


def test_chat_streams_tokens():
    response = client.post(
        "/v1/chat/stream",
        headers=AUTH,
        json={"messages": [{"role": "user", "content": "status"}]},
    )
    assert response.status_code == 200
    assert "data:" in response.text
    assert '"type": "token"' in response.text
    assert '"type": "done"' in response.text


def test_vision_returns_structured_result():
    png = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
        b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    response = client.post(
        "/v1/vision/analyze",
        headers=AUTH,
        files={"image": ("test.png", io.BytesIO(png), "image/png")},
        data={"mode": "identify", "question": "What is this?"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == "identify"
    assert body["result"]["description"]
    assert "confidence" in body["note"].lower()


def test_speech_plan_has_human_pacing():
    response = client.post(
        "/v1/tts/plan",
        headers=AUTH,
        json={"text": "Good morning. **Your battery is at 87 percent.** Shall I plan your day?", "language": "en-IN"},
    )
    assert response.status_code == 200
    body = response.json()
    assert len(body["segments"]) >= 2
    assert "**" not in body["normalized"]
    assert "percent" in body["normalized"]
    pauses = {s["pause_after_ms"] for s in body["segments"]}
    assert len(pauses) >= 1


def test_speech_plan_detects_telugu():
    response = client.post(
        "/v1/tts/plan",
        headers=AUTH,
        json={"text": "నమస్కారం. ఈరోజు మీ షెడ్యూల్ చూపిస్తాను.", "gender": "male"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["language"] == "te-IN"
    assert body["segments"][0]["voice"] == "te-IN-MohanNeural"


def test_tts_headers(monkeypatch):
    async def fake_synth(text, *, voice, rate="+0%", pitch="+0Hz", timeout_seconds=25.0):
        return b"ID3fakeaudio"

    monkeypatch.setattr("app.routes.speech.synthesize_edge", fake_synth)
    response = client.post(
        "/v1/tts",
        headers=AUTH,
        json={"text": "Systems online.", "language": "en-IN"},
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("audio/mpeg")
    assert response.headers["x-voice"] == "en-IN-PrabhatNeural"
    assert response.content == b"ID3fakeaudio"


def test_tts_segments_returns_audio_and_pacing(monkeypatch):
    async def fake_synth(text, *, voice, rate="+0%", pitch="+0Hz", timeout_seconds=25.0):
        return b"ID3clip"

    monkeypatch.setattr("app.routes.speech.synthesize_edge", fake_synth)
    response = client.post(
        "/v1/tts/segments",
        headers=AUTH,
        json={"text": "Good morning. Your battery is at 87 percent. Shall I plan your day?", "language": "en-IN"},
    )
    assert response.status_code == 200
    body = response.json()
    assert len(body["clips"]) == 3
    assert body["clips"][0]["audio_b64"] == "SUQzY2xpcA=="
    assert all(clip["pause_after_ms"] > 0 for clip in body["clips"])


def test_chat_accepts_tools_and_context():
    response = client.post(
        "/v1/chat/stream",
        headers=AUTH,
        json={
            "messages": [{"role": "user", "content": "turn on the flashlight"}],
            "tools": [{"type": "function", "function": {"name": "system_flashlight", "parameters": {}}}],
            "context": "Open task: buy milk",
        },
    )
    assert response.status_code == 200
    assert '"type": "done"' in response.text


def test_chat_rejects_oversized_tool_list():
    response = client.post(
        "/v1/chat/stream",
        headers=AUTH,
        json={
            "messages": [{"role": "user", "content": "hi"}],
            "tools": [{"type": "function", "function": {"name": f"t{i}"}} for i in range(41)],
        },
    )
    assert response.status_code == 422


def test_agent_plan_returns_json():
    response = client.post(
        "/v1/agent/plan",
        headers=AUTH,
        json={"text": "Plan my day", "tools": [{"name": "calendar.read"}]},
    )
    assert response.status_code == 200
    assert "plan" in response.json()
