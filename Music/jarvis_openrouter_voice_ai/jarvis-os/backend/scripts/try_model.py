"""Try one OpenRouter model through the running backend's chat stream."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings

BASE = "http://127.0.0.1:8000"
HEADERS = {"Authorization": f"Bearer {get_settings().device_token}"}
MODEL = sys.argv[1] if len(sys.argv) > 1 else "nvidia/nemotron-3.5-super-vl:free"

payload = {
    "messages": [
        {
            "role": "user",
            "content": "Reply in one short sentence confirming you are online. Then state your model family.",
        }
    ],
    "thinking": False,
    "voice": True,
    "max_tokens": 800,
    "model": MODEL,
}

tokens: list[str] = []
reasoning: list[str] = []
errors: list[str] = []
with httpx.Client(timeout=180.0) as client:
    with client.stream("POST", f"{BASE}/v1/chat/stream", headers=HEADERS, json=payload) as response:
        print("HTTP", response.status_code)
        for line in response.iter_lines():
            if not line.startswith("data:"):
                continue
            event = json.loads(line[5:].strip())
            if event.get("type") == "token":
                tokens.append(event.get("text") or "")
            elif event.get("type") == "reasoning":
                reasoning.append(event.get("text") or "")
            elif event.get("type") == "error":
                errors.append(event.get("message") or "")
            elif event.get("type") not in {"done"}:
                print("EVENT", json.dumps(event)[:400])

print("MODEL:", MODEL)
print("ERRORS:", errors)
print("REASONING_CHARS:", len("".join(reasoning)))
print("TEXT:", "".join(tokens).strip()[:800])
