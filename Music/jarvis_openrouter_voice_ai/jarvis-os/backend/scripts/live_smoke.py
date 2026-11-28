"""Live smoke test against a running J.A.R.V.I.S. backend.

Run from the backend directory after starting uvicorn:
    .venv\\Scripts\\python.exe scripts\\live_smoke.py
"""

from __future__ import annotations

import json
import struct
import sys
import time
import zlib
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings

BASE = "http://127.0.0.1:8000"
HEADERS = {"Authorization": f"Bearer {get_settings().device_token}"}


def make_png(width: int = 256, height: int = 256) -> bytes:
    rows = bytearray()
    for y in range(height):
        rows.append(0)
        for x in range(width):
            dx = x - 88
            dy = y - 96
            in_circle = dx * dx + dy * dy < 52 * 52
            in_square = 160 <= x < 232 and 150 <= y < 222
            if in_circle:
                rows.extend((220, 38, 48))
            elif in_square:
                rows.extend((30, 90, 230))
            else:
                rows.extend((10, 18, 26))

    def chunk(kind: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + kind
            + data
            + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
        )

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(bytes(rows), 9))
        + chunk(b"IEND", b"")
    )


def wait_for_backend() -> dict:
    last: Exception | None = None
    for _ in range(40):
        try:
            response = httpx.get(f"{BASE}/v1/health", timeout=3.0)
            response.raise_for_status()
            return response.json()
        except Exception as exc:  # noqa: BLE001
            last = exc
            time.sleep(1.0)
    raise RuntimeError(f"Backend did not become ready: {last}")


def stream_chat(payload: dict) -> list[dict]:
    events: list[dict] = []
    with httpx.Client(timeout=180.0) as client:
        with client.stream(
            "POST",
            f"{BASE}/v1/chat/stream",
            headers=HEADERS,
            json=payload,
        ) as response:
            response.raise_for_status()
            for line in response.iter_lines():
                if not line.startswith("data:"):
                    continue
                raw = line[5:].strip()
                if not raw:
                    continue
                events.append(json.loads(raw))
    return events


def summarize(events: list[dict]) -> tuple[str, list[dict], str | None]:
    text = "".join(e.get("text") or "" for e in events if e.get("type") == "token")
    calls = [e["tool_call"] for e in events if e.get("type") == "tool_call" and e.get("tool_call")]
    error = next((e.get("message") for e in events if e.get("type") == "error"), None)
    return text.strip(), calls, error


def main() -> int:
    health = wait_for_backend()
    print("HEALTH:", json.dumps(health, ensure_ascii=False))

    text, calls, error = summarize(stream_chat(
        {
            "messages": [
                {
                    "role": "user",
                    "content": "Reply in one short sentence: confirm that you are online and name the model family you run on.",
                }
            ],
            "thinking": False,
            "voice": True,
            "max_tokens": 900,
        }
    ))
    print("CHAT_ERROR:", error)
    print("CHAT_TEXT:", text[:600])
    if not text or error:
        print("CHAT: FAILED")
        return 1
    print("CHAT: OK")

    tools = [
        {
            "type": "function",
            "function": {
                "name": "system_flashlight",
                "description": "Turn the camera torch on or off.",
                "parameters": {
                    "type": "object",
                    "properties": {"on": {"type": "boolean"}},
                    "required": ["on"],
                },
            },
        }
    ]
    text, calls, error = summarize(stream_chat(
        {
            "messages": [{"role": "user", "content": "Turn on the flashlight now."}],
            "thinking": False,
            "voice": False,
            "tools": tools,
            "max_tokens": 900,
        }
    ))
    print("TOOL_ERROR:", error)
    print("TOOL_TEXT:", text[:300])
    print("TOOL_CALLS:", json.dumps(calls, ensure_ascii=False))
    if error or not calls:
        print("TOOL CALLING: FAILED")
    else:
        print("TOOL CALLING: OK")

    try:
        response = httpx.post(
            f"{BASE}/v1/tts/segments",
            headers=HEADERS,
            json={
                "text": "Good evening. All systems are online. This is the J.A.R.V.I.S. voice test.",
                "language": "en-IN",
                "gender": "male",
            },
            timeout=120.0,
        )
        response.raise_for_status()
        body = response.json()
        total = sum(len(c.get("audio_b64", "")) for c in body.get("clips", []))
        print("TTS_CLIPS:", len(body.get("clips", [])), "B64_BYTES:", total)
        print("TTS_PAUSES:", [c.get("pause_after_ms") for c in body.get("clips", [])])
        print("TTS_BREATHS:", [c.get("breath_after") for c in body.get("clips", [])])
        print("TTS: OK" if total > 2000 else "TTS: FAILED (no audio)")
    except Exception as exc:  # noqa: BLE001
        print("TTS: FAILED", type(exc).__name__, str(exc)[:400])

    try:
        png = make_png()
        response = httpx.post(
            f"{BASE}/v1/vision/analyze",
            headers=HEADERS,
            files={"image": ("shapes.png", png, "image/png")},
            data={
                "mode": "describe",
                "question": "What shapes and colors are visible? Answer in one sentence.",
            },
            timeout=180.0,
        )
        response.raise_for_status()
        body = response.json()
        result = body.get("result", {})
        print("VISION_PROVIDER:", body.get("provider"), body.get("model"))
        print("VISION_DESCRIPTION:", str(result.get("description", ""))[:600])
        print("VISION_ANSWER:", str(result.get("answer", ""))[:400])
        ok = bool(result.get("description") or result.get("answer"))
        print("VISION: OK" if ok else "VISION: FAILED (empty result)")
    except Exception as exc:  # noqa: BLE001
        print("VISION: FAILED", type(exc).__name__, str(exc)[:400])

    return 0


if __name__ == "__main__":
    sys.exit(main())
