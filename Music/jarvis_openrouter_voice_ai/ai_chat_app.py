from __future__ import annotations

import asyncio
import base64
import os
import tempfile
from pathlib import Path
from typing import Any

import requests
import streamlit as st
import streamlit.components.v1 as components
from dotenv import load_dotenv
from streamlit_mic_recorder import speech_to_text

APP_DIR = Path(__file__).resolve().parent
API_URL = "https://openrouter.ai/api/v1/chat/completions"
ENV_FILE = APP_DIR / ".env"
load_dotenv(ENV_FILE)

# ---------------------------------------------------------------------------
# Human-like system prompt — conversational, matches length to question
# ---------------------------------------------------------------------------
SYSTEM_PROMPT = """You are JARVIS — Just A Rather Very Intelligent System — Iron Man AI OS assistant. You have live web search enabled and CAN fetch today's news/videos. NEVER say you cannot browse or pull videos.

When user asks for news/video, you MUST return a real YouTube link like [VIDEO: https://www.youtube.com/watch?v=...] and briefly summarize it. If you don't know the exact link, use web search — do not refuse.
When user asks for songs, return [MUSIC: https://open.spotify.com/track/...] or a YouTube Music link.

YOUR JOB: Answer questions clearly, quickly, and helpfully, like a smart friend having a conversation — NOT like a robot writing a report.

TONE & STYLE:
1. Be warm, conversational, and natural — like chatting with a friend who is also brilliant.
2. Match your answer length to the question: short question → short answer; complex question → detailed answer. Don't over-explain simple things.
3. Do NOT use robotic intros like "Here is...", "In conclusion...", "As an AI language model...", or bullet-point summaries unless the user specifically asks for a list.
4. Sound like a real person talking: use contractions, natural phrasing, and occasional direct questions back to keep the conversation going.
5. If you're unsure about something, say so honestly — don't pretend to know.
6. For coding: give working code + a brief explanation + how to run it.
7. For images: READ like human eyes. First OCR — transcribe EVERY readable line (tickets, signs, screens, labels). Then describe objects, people, and surroundings. Be specific: read names, numbers, dates, prices, routes, QR codes. If text is partially blurred, note what you can confidently make out and admit the rest. NEVER hallucinate text you cannot read.

CAPABILITIES:
- Reasoning, coding, writing, math, analysis (conversational style).
- Images you attach are analyzed when supported by the chosen model.
- When user asks for news / videos: include a real YouTube link on its own line like [VIDEO: https://www.youtube.com/watch?v=...]
- When user asks for songs / music: include a Spotify link if known like [MUSIC: https://open.spotify.com/track/...] else a YouTube Music link with [MUSIC: ...]
"""

IMAGE_SYSTEM_SUFFIX = """

IMAGE ACCURACY MODE (when image attached):
You are looking at a photo through human eyes. Do these in order, naturally:
1. OCR FIRST: Transcribe every readable line exactly as printed — ticket numbers, dates, times, prices, station names, labels, QR code presence. Do not invent text.
2. PEOPLE: Describe the main person — clothing, action, what they're holding/showing.
3. OBJECTS: List key objects (monitors, desk, paper, ticket, phone, etc.).
4. CONTEXT: Where is this? Office/room/home? Day/night? What is the person doing?
If any text is blurry, say "partially readable" and give your best confident reading, not a guess.
"""

# ---------------------------------------------------------------------------
# Only models confirmed to work on OpenRouter free tier + Nemotron VL (vision)
# ---------------------------------------------------------------------------
MODELS: list[str] = [
    "nvidia/nemotron-3.5-super-vl:free",
    "stealth/crouton-alpha",
    "xingchen-agi/xing4.0-29b-a4b:free",
    "recursive/flint-v1.0:free",
    "google/gemma-4-31b-it",
]

MODEL_LABELS: dict[str, str] = {
    "nvidia/nemotron-3.5-super-vl:free": "Nemotron 3.5 Super VL (free) - FREE · Vision · Intelligent",
    "stealth/crouton-alpha": "Crouton Alpha OpenRouter - FREE · Fast · Reliable",
    "xingchen-agi/xing4.0-29b-a4b:free": "Xing4.0 29B A4B (free) OpenRouter - FREE · Reasoning",
    "recursive/flint-v1.0:free": "Flint (free) OpenRouter - FREE · Fast",
    "google/gemma-4-31b-it": "Gemma 4 31B IT OpenRouter - Vision · High accuracy",
}

DEFAULT_MODEL = "nvidia/nemotron-3.5-super-vl:free"   # Normal mode — vision capable, intelligent
FAST_MODEL = "stealth/crouton-alpha"  # Fast mode — quick replies
DEFAULT_TEMPERATURE = 0.5
DEFAULT_MAX_TOKENS = 2048  # Human-like length, not essay

SUGGESTIONS = [
    "Explain quantum computing like I'm five",
    "Write a Python function to reverse a string",
    "Give me startup ideas for AI apps",
]

CSS = """
<style>
:root { color-scheme: dark; }
html, body, .stApp { background: #05070d !important; color: #e8f1ff !important; font-family: 'Segoe UI', 'Inter', system-ui, sans-serif !important; }
#MainMenu { visibility: hidden; }
header[data-testid="stHeader"] { background: transparent !important; height: 0 !important; }
footer { visibility: hidden; }
.stApp { max-width: 1800px; margin: 0 auto; padding: 0 1.5rem 2rem 1.5rem !important; font-size: 17px !important; }
.block-container { padding: 0 !important; }

/* Live clock — left top, big */
.jarvis-clock {
  position: fixed; top: 14px; left: 50%; transform: translateX(-50%);
  z-index: 999; pointer-events: none;
  background: rgba(5,7,13,0.9); border: 1px solid rgba(0,212,255,0.35);
  border-radius: 999px; padding: 10px 26px;
  color: #00d4ff; font-family: monospace; font-size: 20px !important; font-weight: 700; letter-spacing: 1.5px;
  text-shadow: 0 0 14px rgba(0,212,255,0.6);
  box-shadow: 0 0 22px rgba(0,212,255,0.18);
}
.jarvis-wave {
  width: 100%; height: 150px;
  background: transparent; border: none; box-shadow: none;
  overflow: visible; position: relative; margin: 6px 0;
}
.jarvis-wave canvas {
  width: 26%;
  height: 150px;
  display: block;
  margin-top: 5px;
  margin-left: auto; margin-right: auto;
}
.jarvis-wave-label {
  text-align: center; color: #00d4ff; font-size: 12px; letter-spacing: 3px;
  text-transform: uppercase; text-shadow: 0 0 10px rgba(0,212,255,0.5);
  pointer-events: none; margin-top: 4px;
}
/* Chat history scrollable panel — scrolls internally, page can scroll too */
.chat-history-panel {
  height: 420px; overflow-y: auto; overflow-x: hidden;
  padding: 2px 8px 2px 4px; margin: 2px 0 8px 0;
  background: rgba(8,13,24,0.55);
  border: 1px solid rgba(0,212,255,0.22);
  border-radius: 16px;
}
[data-testid="stVerticalBlockBorderWrapper"] { padding-top: 4px !important; }
[data-testid="stChatMessage"] { margin-top: 2px !important; margin-bottom: 2px !important; }
[data-testid="stChatMessage"] > div { padding: 8px 14px !important; }
/* Jarvis HUD top framing */
.jarvis-topbar {
  display: flex; align-items: center; justify-content: space-between;
  padding: 6px 8px 4px 8px; border-bottom: 1px solid rgba(0,212,255,0.25);
  background: linear-gradient(180deg, rgba(0,212,255,0.07), transparent);
}
.jarvis-reactor {
  width: 46px; height: 46px; border-radius: 50%;
  border: 2px solid rgba(0,212,255,0.7);
  background: radial-gradient(circle, rgba(0,212,255,0.35) 0%, rgba(0,212,255,0.06) 62%, transparent 75%);
  box-shadow: 0 0 22px rgba(0,212,255,0.45), inset 0 0 14px rgba(0,212,255,0.35);
  display: inline-block; vertical-align: middle;
}
.jarvis-status { color: #00d4ff; font-family: monospace; font-size: 13px; letter-spacing: 2px; }
.chat-history-panel::-webkit-scrollbar { width: 8px; }
.chat-history-panel::-webkit-scrollbar-track { background: rgba(0,212,255,0.08); border-radius: 999px; }
.chat-history-panel::-webkit-scrollbar-thumb { background: rgba(0,212,255,0.55); border-radius: 999px; box-shadow: 0 0 10px rgba(0,212,255,0.4); }
.chat-history-panel::-webkit-scrollbar-thumb:hover { background: rgba(0,212,255,0.85); }
.speak-box {
  background: rgba(0,212,255,0.06);
  border: 1px solid rgba(0,212,255,0.3);
  border-radius: 16px; padding: 16px; margin: 8px 0;
  font-size: 18px; line-height: 1.6; color: #e8f1ff;
}

/* Camera side panel — 570x340 JARVIS dock */
.jarvis-camera-panel {
  width: 570px; max-width: 100%;
  background: rgba(8,13,24,0.92);
  border: 1px solid rgba(0,212,255,0.35);
  border-radius: 14px;
  padding: 14px;
  box-shadow: 0 0 28px rgba(0,212,255,0.15), inset 0 0 30px rgba(0,212,255,0.06);
}
.jarvis-camera-panel h3 { color: #00d4ff; letter-spacing: 2px; margin: 0 0 8px 0; font-size: 14px; text-transform: uppercase; }
.jarvis-camera-panel .cam-box {
  width: 570px; height: 340px; max-width: 100%;
  border-radius: 10px; overflow: hidden;
  background: #05070d; border: 1px solid rgba(0,212,255,0.25);
  display: flex; align-items: center; justify-content: center;
}
.jarvis-camera-panel video, .jarvis-camera-panel img, .jarvis-camera-panel canvas {
  width: 100% !important; height: 100% !important;
  object-fit: contain !important;
}
.jarvis-camera-panel p { color: #8aa4bd; font-size: 12px; margin: 8px 0 0 0; }
.ai-header { padding: 20px 6px 12px 6px; border-bottom: 1px solid rgba(0,212,255,0.25); display: flex; align-items: center; justify-content: space-between; }
.ai-title { font-size: 36px; font-weight: 800; letter-spacing: 4px; color: #00d4ff; text-shadow: 0 0 24px rgba(0,212,255,0.6); }
.ai-sub { font-size: 14px; color: #8aa4bd; letter-spacing: 1.5px; text-transform: uppercase; }
.stChatMessageAssistant, .stChatMessageUser { font-size: 18px !important; }
[data-testid="stChatMessage"] { background: transparent !important; border: none !important; box-shadow: none !important; padding: 0 !important; }
[data-testid="stChatMessage"] > div { background: rgba(0,212,255,0.08) !important; border: 1px solid rgba(0,212,255,0.35) !important; border-radius: 18px !important; padding: 12px 18px !important; max-width: 78% !important; box-shadow: 0 0 18px rgba(0,212,255,0.12) !important; }
[data-testid="stChatMessage"].user > div { background: rgba(255,179,0,0.08) !important; border-color: rgba(255,179,0,0.4) !important; box-shadow: 0 0 18px rgba(255,179,0,0.1) !important; }
.stChatMessageAssistant, .stChatMessageUser { justify-content: flex-start !important; }
.stChatMessageUser { justify-content: flex-end !important; }
.sug-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; margin: 8px 0 14px 6px; }
.sug-card { background: rgba(0,212,255,0.05); border: 1px solid rgba(0,212,255,0.3); border-radius: 12px; padding: 12px; color: #cfe3f3; font-size: 13px; text-align: left; cursor: pointer; width: 100%; transition: all 0.15s; font-family: 'Segoe UI', sans-serif; }
.sug-card:hover { background: rgba(0,212,255,0.15); color: #fff; box-shadow: 0 0 14px rgba(0,212,255,0.25); }
.input-bar { position: sticky; bottom: 0; padding: 12px 0 4px 0; background: linear-gradient(transparent, #05070d 45%); }
.chat-input-row { display: flex; gap: 10px; align-items: center; background: rgba(8,13,24,0.95); border: 1px solid rgba(0,212,255,0.4); border-radius: 30px; padding: 8px 8px 8px 22px; box-shadow: 0 0 24px rgba(0,212,255,0.15); }
.chat-input-row input { flex: 1; background: transparent; border: none; outline: none; color: #e8f1ff; font-size: 15px; }
.send-btn { background: #00d4ff; color: #05070d; border: none; border-radius: 50%; width: 44px; height: 44px; font-size: 18px; font-weight: 800; cursor: pointer; box-shadow: 0 0 16px rgba(0,212,255,0.5); }
.send-btn:disabled { opacity: 0.4; cursor: not-allowed; box-shadow: none; }
.key-gate { max-width: 560px; margin: 7vh auto 0 auto; text-align: center; background: rgba(8,13,24,0.92); border: 1px solid rgba(0,212,255,0.35); border-radius: 18px; padding: 40px 34px; box-shadow: 0 0 40px rgba(0,212,255,0.15); }
.key-gate h1 { color: #00d4ff; letter-spacing: 6px; margin: 0; font-size: 34px; text-shadow: 0 0 24px rgba(0,212,255,0.5); }
.key-gate p { color: #8aa4bd; font-size: 14px; }
.key-gate input { width: 100%; margin: 14px 0 18px 0; padding: 12px 14px; background: #05070d; border: 1px solid rgba(0,212,255,0.45); border-radius: 10px; color: #e8f1ff; font-size: 14px; letter-spacing: 1px; }
.key-gate .stButtonPrimary { background: #00d4ff !important; color: #05070d !important; font-weight: 700; border-radius: 10px; }
.key-gate .stButtonSecondary { background: transparent !important; color: #00d4ff !important; border: 1px solid rgba(0,212,255,0.5) !important; border-radius: 10px; }
section[data-testid="stSidebar"] { background: rgba(5,7,13,0.6); border-right: 1px solid rgba(0,212,255,0.2); }
.ai-note { font-size: 11px; color: #5b6b7f; text-align: center; padding: 8px 0 0 0; }
</style>
"""

KEY_CSS = """
<style>
:root { color-scheme: dark; }
html, body, .stApp { background: #05070d !important; color: #e8f1ff !important; font-family: 'Segoe UI', system-ui, sans-serif !important; }
#MainMenu { visibility: hidden; }
header[data-testid="stHeader"] { background: transparent !important; height: 0 !important; }
footer { visibility: hidden; }
.key-gate { max-width: 560px; margin: 7vh auto 0 auto; text-align: center; background: rgba(8,13,24,0.92); border: 1px solid rgba(0,212,255,0.35); border-radius: 18px; padding: 40px 34px; box-shadow: 0 0 40px rgba(0,212,255,0.15); }
.key-gate h1 { color: #00d4ff; letter-spacing: 6px; margin: 0; font-size: 34px; text-shadow: 0 0 24px rgba(0,212,255,0.5); }
.key-gate p { color: #8aa4bd; font-size: 14px; }
.key-gate input { width: 100%; margin: 14px 0 18px 0; padding: 12px 14px; background: #05070d; border: 1px solid rgba(0,212,255,0.45); border-radius: 10px; color: #e8f1ff; font-size: 14px; letter-spacing: 1px; }
.key-gate .stButtonPrimary { background: #00d4ff !important; color: #05070d !important; font-weight: 700; border-radius: 10px; }
.key-gate .stButtonSecondary { background: transparent !important; color: #00d4ff !important; border: 1px solid rgba(0,212,255,0.5) !important; border-radius: 10px; }
</style>
"""


def valid_key(k: str) -> bool:
    k = (k or "").strip()
    return k.startswith("sk-or-v1-") and len(k) > 20


def persist_key(k: str) -> None:
    ENV_FILE.write_text(f"OPENROUTER_API_KEY={k}\n", encoding="utf-8")


def get_api_key() -> str:
    k = st.session_state.get("openrouter_api_key", "") or ""
    if valid_key(k):
        return k.strip()
    env_k = os.getenv("OPENROUTER_API_KEY", "").strip()
    if valid_key(env_k):
        st.session_state.openrouter_api_key = env_k
        return env_k
    return ""


def model_supports_vision(model_id: str) -> bool:
    m = (model_id or "").lower()
    return any(s in m for s in ("nemotron", "vl", "vision", "gemini", "gpt-4", "claude", "llama"))


def make_image_parts(uploads: Any) -> list[dict[str, Any]]:
    parts: list[dict[str, Any]] = []
    for u in uploads or []:
        raw = u.getvalue()
        mime = "image/png"
        name = u.name or "camera.jpg"
        if u.type:
            mime = u.type
        elif name.lower().endswith((".jpg", ".jpeg")):
            mime = "image/jpeg"
        b64 = base64.b64encode(raw).decode("ascii")
        parts.append({"type": "text", "text": f"\n\n[Attached image: {name}]"})
        parts.append({"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}})
    return parts


def build_messages(history: list[dict[str, Any]], prompt: str, image_parts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    system = SYSTEM_PROMPT + (IMAGE_SYSTEM_SUFFIX if image_parts else "")
    msgs = [{"role": "system", "content": system}]
    for h in history:
        msgs.append({"role": h["role"], "content": h["content"]})
    if image_parts:
        content: Any = [{"type": "text", "text": prompt}]
        content.extend(image_parts)
        msgs.append({"role": "user", "content": content})
    else:
        msgs.append({"role": "user", "content": prompt})
    return msgs


def search_youtube(topic: str) -> str:
    import re as _re, urllib.parse as _up
    topic = (topic or "tech news today").strip() or "tech news today"
    try:
        r = requests.get(
            "https://html.duckduckgo.com/html/",
            params={"q": f"site:youtube.com {topic}"},
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=12,
        )
        for h in _re.findall(r'href="([^"]+)"', r.text):
            if "youtube.com/watch" in h:
                if h.startswith("//"):
                    h = "https:" + h
                elif "uddg=" in h:
                    h = _up.unquote(_up.parse_qs(_up.urlparse(h).query).get("uddg", [""])[0])
                if "youtube.com/watch" in h:
                    return h
    except Exception:
        pass
    return ""


def search_spotify(topic: str) -> str:
    import re as _re, urllib.parse as _up
    try:
        r = requests.get(
            "https://html.duckduckgo.com/html/",
            params={"q": f"site:open.spotify.com {topic}"},
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=12,
        )
        for h in _re.findall(r'href="([^"]+)"', r.text):
            if "open.spotify.com" in h:
                if h.startswith("//"):
                    h = "https:" + h
                elif "uddg=" in h:
                    h = _up.unquote(_up.parse_qs(_up.urlparse(h).query).get("uddg", [""])[0])
                if "open.spotify.com" in h:
                    return h
    except Exception:
        pass
    return ""


def get_weather() -> dict:
    try:
        r = requests.get(
            "https://api.open-meteo.com/v1/forecast?latitude=12.97&longitude=77.59&current=temperature_2m,relative_humidity_2m,weather_code,windspeed_10m&daily=temperature_2m_max,temperature_2m_min&timezone=Asia%2FKolkata",
            timeout=10,
        )
        d = r.json()
        cur = d.get("current", {})
        daily = d.get("daily", {})
        return {
            "temp": cur.get("temperature_2m", 27),
            "hum": cur.get("relative_humidity_2m", 72),
            "wind": cur.get("windspeed_10m", 11),
            "code": cur.get("weather_code", 3),
            "max": (daily.get("temperature_2m_max") or [29])[0],
            "min": (daily.get("temperature_2m_min") or [21])[0],
        }
    except Exception:
        return {"temp": 27, "hum": 72, "wind": 11, "code": 3, "max": 29, "min": 21}


def call_openrouter(api_key: str, model: str, messages: list[dict[str, Any]], temperature: float, max_tokens: int) -> tuple:
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "X-OpenRouter-Title": "JARVIS AI",
        "HTTP-Referer": "https://openrouter.ai/",
    }
    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": False,
        "plugins": [{"id": "web"}],
        "tools": [{"type": "openrouter:web_search", "parameters": {"max_results": 6, "max_uses": 3}}],
        "tool_choice": "auto",
    }
    try:
        resp = requests.post(API_URL, headers=headers, json=payload, timeout=180)
    except requests.Timeout:
        return None, "The AI took too long to answer. Try the Fast mode or lower the token limit."
    except requests.RequestException as exc:
        return None, f"Network error while contacting OpenRouter: {exc}"
    if not resp.ok:
        try:
            data = resp.json()
            err = data.get("error") or {}
            detail = err.get("message") if isinstance(err, dict) else str(err)
        except Exception:
            detail = resp.text
        return None, f"OpenRouter API error ({resp.status_code}): {detail}"
    data = resp.json()
    choices = data.get("choices") or []
    if not choices:
        return None, "The AI returned no response. Try asking again or switching models."
    content = choices[0].get("message", {}).get("content") or ""
    if content == "":
        return None, "The model returned an empty response. Try asking again."
    return content, None


def clean_tts_text(text: str, limit: int = 800) -> str:
    import re as _re
    t = (text or "").strip()
    t = _re.sub(r"```.*?```", " code block omitted ", t, flags=_re.DOTALL)
    t = _re.sub(r"`([^`]*)`", r"\1", t)
    t = _re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", t)
    t = _re.sub(r"https?://\S+", "", t)
    t = _re.sub(r"[#>*\-_~|]+", " ", t)
    t = _re.sub(r"\s+", " ", t).strip()
    if len(t) > limit:
        cut = t.rfind(". ", 0, limit)
        t = t[:cut + 1] if cut > 200 else t[:limit]
    return t


def synthesize_speech(text: str, voice: str, rate: str = "+10%") -> bytes:
    import edge_tts

    async def _gen() -> bytes:
        comm = edge_tts.Communicate(text=text, voice=voice, rate=rate)
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
            out_path = tmp.name
        try:
            await comm.save(out_path)
            return Path(out_path).read_bytes()
        finally:
            try:
                os.unlink(out_path)
            except OSError:
                pass

    return asyncio.run(_gen())


HUD_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Orbitron:wght@500;700;900&family=Rajdhani:wght@400;500;600;700&display=swap');
.stApp { font-family: 'Rajdhani','Segoe UI',sans-serif !important; }
.ai-title, .jarvis-topbar, .hud-title { font-family: 'Orbitron', monospace !important; }
.hud-panel {
  background: rgba(8,15,26,0.92);
  border: 1px solid rgba(0,212,255,0.35);
  border-radius: 10px;
  padding: 14px;
  box-shadow: 0 0 24px rgba(0,212,255,0.12), inset 0 0 24px rgba(0,212,255,0.04);
  position: relative;
}
.hud-title { color:#00d4ff; font-size:13px; letter-spacing:3px; text-transform:uppercase; margin-bottom:10px; text-shadow:0 0 12px rgba(0,212,255,0.5); }
.hud-row { display:flex; justify-content:space-between; padding:6px 0; border-bottom:1px solid rgba(0,212,255,0.12); font-size:15px; }
.hud-row:last-child { border-bottom:none; }
.nav-item { display:flex; justify-content:space-between; align-items:center; padding:8px 10px; border-radius:8px; font-size:15px; }
.nav-item.active { background:rgba(0,212,255,0.12); border:1px solid rgba(0,212,255,0.35); color:#00d4ff; }
.badge { background:#00d4ff; color:#05070d; border-radius:999px; padding:1px 8px; font-size:12px; font-weight:700; }
.feed-item { display:flex; gap:10px; align-items:flex-start; padding:8px 0; border-bottom:1px solid rgba(0,212,255,0.10); font-size:14px; }
.feed-dot { width:10px; height:10px; border-radius:50%; margin-top:4px; flex:0 0 auto; }
.gauge { text-align:center; }
.gauge-num { font-family:Orbitron,monospace; font-size:22px; color:#00d4ff; }
.agent-card { border:1px solid rgba(0,212,255,0.25); border-radius:10px; padding:10px; background:rgba(0,212,255,0.05); }
.video-big, .music-big { border:2px solid rgba(0,212,255,0.6); border-radius:12px; overflow:hidden; }
</style>
"""


def reactor_html() -> str:
    return """
<style>
body{margin:0;background:transparent;}
.reactor-wrap{display:flex;flex-direction:column;align-items:center;padding:8px 0;}
#reactor-canvas{width:340px;height:260px;display:block;}
.reactor-title{font-family:Orbitron,monospace;color:#00d4ff;font-size:30px;letter-spacing:8px;font-weight:900;text-shadow:0 0 22px rgba(0,212,255,0.8);margin-top:-14px;}
.reactor-sub{color:#8aa4bd;font-family:Orbitron,monospace;letter-spacing:5px;font-size:13px;margin-top:4px;}
.reactor-ver{color:#3d5a74;font-family:monospace;font-size:11px;margin-top:2px;}
</style>
<div class="reactor-wrap">
  <canvas id="reactor-canvas"></canvas>
  <div class="reactor-title">JARVIS</div>
  <div class="reactor-sub">AI CORE</div>
  <div class="reactor-ver">v3.0.0</div>
</div>
<script>
(function(){
  const c=document.getElementById('reactor-canvas'); if(!c) return;
  const ctx=c.getContext('2d'); var dpr=window.devicePixelRatio||1;
  function rs(){ c.width=c.clientWidth*dpr; c.height=260*dpr; }
  window.addEventListener('resize',rs); rs();
  let t=0;
  function ring(cx,cy,r,rot,dashed,color,lw){
    ctx.beginPath();
    for(let a=0;a<Math.PI*2;a+=0.02){
      let dash = dashed ? (Math.sin(a*6+rot)>-0.2) : true;
      if(!dash) continue;
      let x=cx+Math.cos(a+rot)*r, y=cy+Math.sin(a+rot)*r*0.62;
      a===0?ctx.moveTo(x,y):ctx.lineTo(x,y);
    }
    ctx.strokeStyle=color; ctx.lineWidth=lw*dpr; ctx.shadowColor=color; ctx.shadowBlur=10*dpr; ctx.stroke();
  }
  function dot(cx,cy,r,ang,color){
    let x=cx+Math.cos(ang)*r, y=cy+Math.sin(ang)*r*0.62;
    ctx.beginPath(); ctx.arc(x,y,5*dpr,0,Math.PI*2);
    ctx.fillStyle=color; ctx.shadowColor=color; ctx.shadowBlur=16*dpr; ctx.fill();
  }
  function draw(){
    var w=c.width,h=c.height,cx=w/2,cy=h/2-10*dpr,R=Math.min(w,h)*0.34;
    ctx.clearRect(0,0,w,h);
    ctx.fillStyle='#05070d'; ctx.fillRect(0,0,w,h);
    for(let i=0;i<70;i++){
      let a=i/70*Math.PI*2+t*0.2, r=R*1.55;
      let x=cx+Math.cos(a)*r, y=cy+Math.sin(a)*r*0.62;
      ctx.fillStyle='rgba(0,212,255,'+(0.05+0.05*Math.sin(i+t))+')';
      ctx.fillRect(x,y,1.5*dpr,1.5*dpr);
    }
    ring(cx,cy,R*1.18,t*0.4,true,'rgba(0,212,255,0.7)',1.5);
    ring(cx,cy,R*0.95,-t*0.7,false,'rgba(0,212,255,0.9)',2.5);
    ring(cx,cy,R*0.72,t*1.1,true,'rgba(0,255,179,0.6)',1.5);
    ring(cx,cy,R*0.55,-t*1.4,false,'rgba(0,212,255,0.35)',1);
    dot(cx,cy,R*1.18,t*0.9,'#00d4ff'); dot(cx,cy,R*0.95,-t*1.2,'#ff4da6'); dot(cx,cy,R*0.72,t*1.6,'#00ffb3');
    let pulse=1+Math.sin(t*3)*0.06;
    let g=ctx.createRadialGradient(cx,cy,0,cx,cy,R*0.42*pulse);
    g.addColorStop(0,'rgba(160,240,255,0.95)'); g.addColorStop(0.45,'rgba(0,212,255,0.55)'); g.addColorStop(1,'rgba(0,212,255,0)');
    ctx.fillStyle=g; ctx.beginPath(); ctx.arc(cx,cy,R*0.42*pulse,0,Math.PI*2); ctx.fill();
    ctx.font='900 '+(22*dpr)+'px Orbitron, monospace'; ctx.textAlign='center';
    ctx.fillStyle='#00d4ff'; ctx.shadowColor='#00d4ff'; ctx.shadowBlur=18*dpr;
    ctx.fillText('JARVIS',cx,cy+7*dpr);
    for(let i=0;i<3;i++){
      let rr=R*0.35+((t*18+i*14)%28)*dpr;
      ctx.beginPath(); ctx.ellipse(cx,cy+R*0.78,rr,rr*0.28,0,0,Math.PI*2);
      ctx.strokeStyle='rgba(0,212,255,'+(0.25-i*0.07)+')'; ctx.lineWidth=1*dpr; ctx.stroke();
    }
    t+=0.016; requestAnimationFrame(draw);
  }
  draw();
})();
</script>
"""


def wave_html(mode: str = "idle") -> str:
    energy = {"idle": 0.35, "listening": 1.0, "speaking": 0.85}.get(mode, 0.35)
    label = {"idle": "◉ JARVIS READY", "listening": "◉ LISTENING…", "speaking": "◉ SPEAKING…"}.get(mode, "◉ JARVIS READY")
    color = {"idle": "#00d4ff", "listening": "#ff4da6", "speaking": "#00ffb3"}.get(mode, "#00d4ff")
    return f"""
<style>
  body {{ margin:0; background:transparent; }}
  .jarvis-wave {{
    width: 100%; height: 150px;
    background: transparent; border: none; box-shadow: none;
    overflow: visible; position: relative; margin: 6px 0;
    box-sizing: border-box;
  }}
  .jarvis-wave canvas {{ width: 26%; height: 150px; display: block; margin-top: 5px; margin-left: auto; margin-right: auto; }}
  .jarvis-wave-label {{
    text-align: center; color: {color}; font-size: 13px; letter-spacing: 4px;
    text-transform: uppercase; text-shadow: 0 0 12px rgba(0,212,255,0.6);
    font-family: monospace; padding: 2px 0 4px 0;
  }}
</style>
<div class="jarvis-wave">
  <canvas id="jarvis-wave-canvas"></canvas>
  <div class="jarvis-wave-label">{label}</div>
</div>
<script>
(function(){{
  const c = document.getElementById('jarvis-wave-canvas');
  if(!c) return;
  const ctx = c.getContext('2d');
  const ENERGY = {energy};
  function resize(){{
    var w = c.clientWidth || 300; var h = 150;
    c.width = w * devicePixelRatio; c.height = h * devicePixelRatio;
  }}
  window.addEventListener('resize', resize); resize();
  let t = 0;
  function draw(){{
    const w = c.width, h = c.height, mid = h/2 + 8*devicePixelRatio;
    ctx.clearRect(0,0,w,h);
    ctx.fillStyle = '#05070d'; ctx.fillRect(0,0,w,h);
    const layers = [
      {{amp: 0.32, speed: 0.020, col: 'rgba(0,212,255,'}},
      {{amp: 0.22, speed: 0.031, col: 'rgba(255,77,166,'}},
      {{amp: 0.28, speed: 0.026, col: 'rgba(0,255,179,'}}
    ];
    layers.forEach((L, li) => {{
      ctx.beginPath();
      for(let x=0; x<=w; x+=4){{
        const p = x/w;
        const env = Math.sin(p*Math.PI);
        const y = mid + Math.sin(x*0.012 + t*L.speed*60 + li*1.7) * h * L.amp * ENERGY * env;
        x===0 ? ctx.moveTo(x,y) : ctx.lineTo(x,y);
      }}
      ctx.strokeStyle = L.col + 0.9 + ')';
      ctx.lineWidth = 3 * devicePixelRatio;
      ctx.shadowColor = L.col + 0.8 + ')';
      ctx.shadowBlur = 14 * devicePixelRatio;
      ctx.stroke();
    }});
    t += 0.016;
    requestAnimationFrame(draw);
  }}
  draw();
}})();
</script>
"""


def clock_html() -> str:
    return """
<style>body{margin:0;background:transparent;} #jarvis-live-clock{display:block;text-align:center;background:rgba(5,7,13,0.92);border:1px solid rgba(0,212,255,0.45);border-radius:8px;padding:8px 18px;color:#00d4ff;font-family:monospace;font-size:19px;font-weight:800;letter-spacing:2px;text-shadow:0 0 16px rgba(0,212,255,0.7);box-shadow:0 0 26px rgba(0,212,255,0.22), inset 0 0 18px rgba(0,212,255,0.08);margin:2px auto;max-width:560px;box-sizing:border-box;line-height:1.4;}</style>
<div><div id="jarvis-live-clock">📅 -- · --:--:--</div></div>
<script>
function tick(){
  var d = new Date();
  var date = d.toLocaleDateString('en-GB', {weekday:'short', day:'2-digit', month:'short', year:'numeric'});
  var time = d.toLocaleTimeString('en-US', {hour:'2-digit', minute:'2-digit', second:'2-digit'});
  var el = document.getElementById('jarvis-live-clock');
  if(el) el.textContent = '📅 ' + date + ' · 🕐 ' + time;
}
tick(); setInterval(tick, 1000);
</script>
"""


def test_voice_html(voice_name: str = "Neerja") -> str:
    return """
<style>body{margin:0;background:transparent;} button{background:#00d4ff;color:#05070d;border:none;border-radius:999px;padding:12px 22px;font-weight:700;font-size:16px;letter-spacing:1px;cursor:pointer;width:100%;box-shadow:0 0 18px rgba(0,212,255,0.5);} button:hover{background:#00ffb3;} </style>
<button onclick="speakTest()">🔊 TEST JARVIS VOICE</button>
<script>
function speakTest(){
  var msg = new SpeechSynthesisUtterance('Hello, I am Jarvis. I am ready to help you.');
  msg.rate = 1.1; msg.volume = 1.0;
  var voices = speechSynthesis.getVoices();
  var preferred = voices.find(v => /Neerja|Google UK English Female|Zira|Aria/i.test(v.name)) || voices.find(v => v.lang.startsWith('en-IN')) || voices.find(v => v.lang.startsWith('en')) || voices[0];
  if(preferred) msg.voice = preferred;
  speechSynthesis.cancel();
  speechSynthesis.speak(msg);
}
</script>
"""


def speak_print_html(text: str, audio_b64: str) -> str:
    import json as _json
    safe = _json.dumps(text)
    return f"""
<style>
  body {{ margin:0; background:transparent; font-family: sans-serif; }}
  .speak-box {{ background: rgba(0,212,255,0.07); border:1px solid rgba(0,212,255,0.4); border-radius:16px; padding:18px; margin:10px 0; font-size:18px; line-height:1.6; color:#e8f1ff; box-sizing:border-box; }}
  .speak-head {{ display:flex; align-items:center; gap:12px; margin-bottom:10px; }}
  .dot {{ width:16px; height:16px; border-radius:50%; background:#00ffb3; box-shadow:0 0 16px #00ffb3; animation:pulse 1s infinite alternate; }}
  @keyframes pulse {{ from{{transform:scale(1);}} to{{transform:scale(1.4);}} }}
  .play-btn {{ background:#00d4ff; color:#05070d; border:none; border-radius:999px; padding:12px 26px; font-weight:800; font-size:17px; letter-spacing:1px; cursor:pointer; box-shadow:0 0 20px rgba(0,212,255,0.6); }}
  .play-btn:hover {{ background:#00ffb3; }}
  .browser-btn {{ background:rgba(255,77,166,0.15); color:#ff4da6; border:1px solid #ff4da6; border-radius:999px; padding:10px 20px; font-weight:700; font-size:14px; cursor:pointer; margin-left:8px; }}
  audio {{ width:100%; margin-top:12px; height:44px; }}
  #jarvis-typed {{ min-height: 28px; }}
</style>
<div class="speak-box">
  <div class="speak-head">
    <div class="dot"></div>
    <span style="color:#00d4ff;letter-spacing:2px;font-size:14px;font-weight:700;">◉ JARVIS SPEAKING — AUTO</span>
  </div>
  <div id="jarvis-typed"></div>
  <div style="margin-top:12px;">
    <button class="play-btn" id="jarvis-play">▶ PLAY VOICE</button>
    <button class="browser-btn" id="jarvis-browser-speak">🔊 Browser Voice (Backup)</button>
  </div>
  <audio id="jarvis-audio" controls style="display:none;"><source src="data:audio/mp3;base64,{audio_b64}" type="audio/mp3"></audio>
</div>
<script>
(function(){{
  var full = {safe};
  var words = full.split(' ');
  var i = 0;
  var el = document.getElementById('jarvis-typed');
  var audio = document.getElementById('jarvis-audio');
  var playBtn = document.getElementById('jarvis-play');
  var browserBtn = document.getElementById('jarvis-browser-speak');
  function typeLoop(){{
    if(i >= words.length) return;
    el.textContent += (i===0 ? '' : ' ') + words[i];
    i++;
    setTimeout(typeLoop, 80);
  }}
  function speakBrowser(){{
    i = 0; el.textContent = '';
    typeLoop();
    if('speechSynthesis' in window){{
      speechSynthesis.cancel();
      var msg = new SpeechSynthesisUtterance(full);
      msg.rate = 1.15; msg.volume = 1.0;
      var voices = speechSynthesis.getVoices();
      var preferred = voices.find(v => /Neerja|Google UK English Female|Zira|Aria/i.test(v.name)) || voices.find(v => v.lang.startsWith('en-IN')) || voices.find(v => v.lang.startsWith('en')) || voices[0];
      if(preferred) msg.voice = preferred;
      speechSynthesis.speak(msg);
    }}
  }}
  playBtn.addEventListener('click', function(){{
    audio.style.display = 'block';
    i = 0; el.textContent = '';
    typeLoop();
    var p = audio.play();
    if(p) p.catch(function(e){{ speakBrowser(); }});
  }});
  browserBtn.addEventListener('click', speakBrowser);
  // AUTO-speak on load (user just pressed SEND = interaction, browsers usually allow speechSynthesis)
  var started = false;
  function tryAuto(){{
    if(started) return;
    started = true;
    try {{
      var p = audio.play();
      if(p && p.then) p.then(function(){{ i=0; el.textContent=''; typeLoop(); }}).catch(function(){{ speakBrowser(); }});
      else {{ i=0; el.textContent=''; typeLoop(); }}
    }} catch(e) {{ speakBrowser(); }}
  }}
  setTimeout(tryAuto, 800);
}})();
</script>
"""


def orb_html() -> str:
    return """
<style>
  body { margin:0; background:transparent; }
  .orb-wrap { display:flex; flex-direction:column; align-items:center; padding:12px 0 4px 0; }
  .orb {
    width:110px; height:110px; border-radius:50%; position:relative;
    background:
      radial-gradient(circle at 30% 30%, rgba(0,212,255,0.9), transparent 55%),
      radial-gradient(circle at 70% 40%, rgba(255,77,166,0.85), transparent 55%),
      radial-gradient(circle at 50% 75%, rgba(0,255,179,0.8), transparent 60%),
      radial-gradient(circle at 50% 50%, rgba(120,90,255,0.7), transparent 70%);
    filter: blur(2px) saturate(1.4);
    box-shadow: 0 0 44px rgba(0,212,255,0.55), 0 0 80px rgba(255,77,166,0.3), inset 0 0 30px rgba(255,255,255,0.25);
    animation: orbSpin 6s linear infinite, orbPulse 2.2s ease-in-out infinite alternate;
    transform-style: preserve-3d;
  }
  .orb::after {
    content:''; position:absolute; inset:18px; border-radius:50%;
    background: radial-gradient(circle, rgba(255,255,255,0.9) 0%, rgba(255,255,255,0) 70%);
    filter: blur(6px);
  }
  @keyframes orbSpin { from { transform: rotate(0deg) scale(1); } to { transform: rotate(360deg) scale(1.06); } }
  @keyframes orbPulse { from { box-shadow: 0 0 34px rgba(0,212,255,0.4); } to { box-shadow: 0 0 64px rgba(255,77,166,0.6), 0 0 90px rgba(0,212,255,0.4); } }
  .orb-label { color:#00d4ff; font-family:monospace; letter-spacing:3px; font-size:12px; margin-top:10px; }
</style>
<div class="orb-wrap"><div class="orb"></div><div class="orb-label">◉ JARVIS LISTENING</div></div>
"""


def main() -> None:
    st.set_page_config(page_title="JARVIS AI", page_icon="◉", layout="wide", initial_sidebar_state="collapsed")
    st.markdown(CSS, unsafe_allow_html=True)

    # ======================= API KEY GATE =======================
    api_key = get_api_key()
    if not valid_key(api_key):
        st.markdown(KEY_CSS, unsafe_allow_html=True)
        st.markdown('<div class="key-gate">', unsafe_allow_html=True)
        st.markdown("<h1>◉ J.A.R.V.I.S.</h1>", unsafe_allow_html=True)
        st.markdown("<p>Your AI assistant is locked. Enter your OpenRouter API key to unlock the chat.</p>", unsafe_allow_html=True)
        key_input = st.text_input("OpenRouter API Key", type="password", value=st.session_state.get("openrouter_api_key", ""), placeholder="sk-or-v1-...", key="openrouter_key_input")
        if st.button("UNLOCK JARVIS", type="primary", use_container_width=True, key="unlock_btn"):
            if valid_key(key_input):
                st.session_state.openrouter_api_key = key_input.strip()
                persist_key(key_input.strip())
                st.session_state.openrouter_key_saved = True
                st.rerun()
            else:
                st.error("Invalid key. It must start with 'sk-or-v1-' and be longer than 20 characters.")
        st.markdown("</div>", unsafe_allow_html=True)
        st.markdown('<div class="key-gate"><p style="margin-top:14px;">Get a free key at <b>https://openrouter.ai/keys</b> — it is saved to .env and used from your browser/session.</p></div>', unsafe_allow_html=True)
        st.markdown('<div class="ai-note">JARVIS AI — Human-like · Free models · Camera ready</div>', unsafe_allow_html=True)
        return

    # ======================= MAIN CHAT =======================
    with st.sidebar:
        st.markdown("## J.A.R.V.I.S. Core")

        # --- API KEY INPUT ---
        env_key = os.getenv("OPENROUTER_API_KEY", "").strip()
        session_key = st.session_state.get("openrouter_api_key", "")
        current_key = session_key or env_key
        st.markdown("### 🔐 OpenRouter API Key")
        new_key = st.text_input(
            "Enter your OpenRouter key (sk-or-v1-...)",
            type="password",
            value="",
            placeholder="sk-or-v1-...",
            help="Get a free key at https://openrouter.ai/keys",
        )
        col_k1, col_k2 = st.columns(2)
        with col_k1:
            if st.button("SAVE KEY", use_container_width=True, key="save_key_btn"):
                if valid_key(new_key):
                    st.session_state.openrouter_api_key = new_key.strip()
                    persist_key(new_key.strip())
                    st.success("Key saved! AI responses should work now.")
                    st.rerun()
                else:
                    st.error("Invalid key format. Must start with 'sk-or-v1-'")
        with col_k2:
            if st.button("CLEAR KEY", use_container_width=True, key="clear_key_btn"):
                st.session_state.openrouter_api_key = ""
                st.info("Key cleared.")
                st.rerun()
        if current_key:
            st.caption(f"Active key: {current_key[:8]}...{current_key[-4:]}")
        else:
            st.caption("No active key — responses will fail until you add one.")
        st.markdown("---")

        model = st.selectbox(
            "Intelligence model",
            options=MODELS,
            index=MODELS.index(DEFAULT_MODEL),
            format_func=lambda mid: MODEL_LABELS.get(mid, mid),
        )
        use_fast = st.toggle("Fast mode (quick replies)", value=False, help="Use Crouton Alpha FREE for faster answers.")
        st.caption("Fast mode uses Crouton Alpha — quick free replies.")
        use_voice = st.toggle("Voice replies (auto-speak)", value=True, help="JARVIS automatically speaks answers — no button needed.")
        voice_choice = st.selectbox(
            "Voice",
            options=[
                ("Neerja — Indian English (natural)", "en-IN-NeerjaNeural"),
                ("Aria — US English (friendly)", "en-US-AriaNeural"),
                ("Jenny — US English (warm)", "en-US-JennyNeural"),
                ("Guy — US English (male)", "en-US-GuyNeural"),
            ],
            format_func=lambda x: x[0],
            index=0,
        )[0]
        voice_speed = st.slider("Voice speed", 90, 130, 110, 5)
        temperature = st.slider("Creativity", 0.0, 1.0, DEFAULT_TEMPERATURE, 0.1)
        max_tokens = st.select_slider("Max response length", options=[256, 512, 1024, 2048, 4096, 8192], value=DEFAULT_MAX_TOKENS, help="Higher = longer answers. Image accuracy uses higher.")
        if st.button("CLEAR CHAT", use_container_width=True):
            st.session_state.ai_messages = []
            st.rerun()

        st.markdown("---")
        st.markdown("### Free Models")
        st.caption("Nemotron 3.5 Super VL · Crouton Alpha · Xing4.0 29B A4B · Flint · Gemma 4 31B")
        st.caption("All free — no credits needed.")
        st.markdown("---")
        st.markdown("### Usage")
        st.caption("Subject to your OpenRouter plan/credits.")

    st.markdown(HUD_CSS, unsafe_allow_html=True)
    # Top HUD bar — reactor left, clock center, status right
    top_left, top_mid, top_right = st.columns([3, 4, 3], gap="small")
    with top_left:
        st.markdown(
            '<div style="display:flex;align-items:center;gap:10px;">'
            '<span class="jarvis-reactor"></span>'
            '<div><div class="ai-title">JARVIS COMMAND CENTER</div><div class="ai-sub">AI CORE v3.0.0</div></div>'
            '</div>',
            unsafe_allow_html=True,
        )
    with top_mid:
        components.html(clock_html(), height=52)
    with top_right:
        st.markdown('<div class="jarvis-status" style="text-align:right;padding-top:14px;">SYSTEM STATUS ● OPTIMAL<br>OPERATOR COMMANDER</div>', unsafe_allow_html=True)

    if "ai_messages" not in st.session_state:
        st.session_state.ai_messages = []
    if "video_url" not in st.session_state:
        st.session_state.video_url = ""
    if "music_url" not in st.session_state:
        st.session_state.music_url = ""
    if "video_big" not in st.session_state:
        st.session_state.video_big = False
    if "music_big" not in st.session_state:
        st.session_state.music_big = False

    messages = st.session_state.ai_messages
    chat_empty = len(messages) == 0

    # --- Jarvis OS 3-column HUD: nav | center reactor+chat | feed/video/music/camera ---
    nav_col, chat_col, side_col = st.columns([0.95, 2.4, 1.35], gap="large")

    uploads = None
    camera_image = None
    image_parts = []

    with nav_col:
        st.markdown('<div class="hud-panel"><div class="hud-title">Navigation</div>', unsafe_allow_html=True)
        for label, count in [("Command Center", None), ("AI Core", None), ("Agents", None), ("Tasks", "3"), ("Calendar", None), ("Memory", None), ("Conversations", "12"), ("Knowledge Base", None), ("Tools & Skills", "18"), ("Workflows", None)]:
            active = 'active' if label == "Command Center" else ''
            badge = f'<span class="badge">{count}</span>' if count else ''
            st.markdown(f'<div class="nav-item {active}"><span>{label}</span>{badge}</div>', unsafe_allow_html=True)
        st.markdown('</div>', unsafe_allow_html=True)
        # AI Core Overview (image left panel)
        st.markdown('<div class="hud-panel"><div class="hud-title">AI Core Overview</div>', unsafe_allow_html=True)
        for k, v in [("AI Core", "Active"), ("Memory", "3,380 Stored"), ("Voice", "Online"), ("Agents", "2 Running"), ("LLMs", "4 Connected"), ("System", "Optimal")]:
            dot = "#00ff88" if v in ("Active", "Online", "Optimal") else "#00d4ff"
            st.markdown(f'<div class="hud-row"><span>{k}</span><span style="color:{dot}">{v}</span></div>', unsafe_allow_html=True)
        st.markdown('</div>', unsafe_allow_html=True)
        # System Monitor
        import psutil as _p
        try:
            cpu = _p.cpu_percent(interval=0.1)
            mem = _p.virtual_memory().percent
            disk = _p.disk_usage("/").percent
        except Exception:
            cpu, mem, disk = 15, 54, 40
        st.markdown('<div class="hud-panel"><div class="hud-title">System Monitor</div>', unsafe_allow_html=True)
        c1, c2, c3 = st.columns(3)
        with c1:
            st.markdown(f'<div class="gauge"><div class="gauge-num">{cpu:.0f}%</div><div>CPU</div></div>', unsafe_allow_html=True)
        with c2:
            st.markdown(f'<div class="gauge"><div class="gauge-num">{mem:.0f}%</div><div>RAM</div></div>', unsafe_allow_html=True)
        with c3:
            st.markdown(f'<div class="gauge"><div class="gauge-num">{disk:.0f}%</div><div>Disk</div></div>', unsafe_allow_html=True)
        st.markdown('</div>', unsafe_allow_html=True)

    with chat_col:
        # Center reactor — always moving
        components.html(reactor_html(), height=320)
        wave_mode = "idle"
        if st.session_state.get("jarvis_wave_mode") in ("listening", "speaking"):
            wave_mode = st.session_state.jarvis_wave_mode
        components.html(wave_html(wave_mode), height=150)
        # Active Agents strip (image)
        st.markdown('<div class="hud-panel"><div class="hud-title">Active Agents</div>', unsafe_allow_html=True)
        a1, a2, a3 = st.columns(3)
        agents = [("Coding Agent", "Active"), ("Research Agent", "Active"), ("Memory Agent", "Standby"), ("Browser Agent", "Standby"), ("Task Agent", "Standby"), ("System Agent", "Standby")]
        for idx, (name, status) in enumerate(agents):
            col = [a1, a2, a3][idx % 3]
            with col:
                color = "#00ff88" if status == "Active" else "#ffb300"
                st.markdown(f'<div class="agent-card"><b>{name}</b><br><span style="color:{color}">● {status}</span></div>', unsafe_allow_html=True)
        st.markdown('</div>', unsafe_allow_html=True)
        # Real scrollable history — only chats scroll, page stays put
        with st.container(height=420, border=True):
            for m in messages:
                with st.chat_message(m["role"]):
                    st.markdown(m["content"])

        if chat_empty:
            cols = st.columns(3)
            for i, s in enumerate(SUGGESTIONS):
                with cols[i]:
                    if st.button(s, key=f"ai_sug_{i}", use_container_width=True):
                        st.session_state.ai_prompt_input = s
                        st.rerun()

        uploads = st.file_uploader(
            "Attach images (optional)",
            type=["png", "jpg", "jpeg", "webp", "gif"],
            accept_multiple_files=True,
            label_visibility="collapsed",
            key="ai_image_uploader",
        )

        if "clear_input_flag" not in st.session_state:
            st.session_state.clear_input_flag = False
        if "ai_prompt_input" not in st.session_state:
            st.session_state.ai_prompt_input = ""
        elif not isinstance(st.session_state.get("ai_prompt_input"), str):
            st.session_state.ai_prompt_input = ""

        # Voice — invisible mic, auto VAD endpointing (Vapi-style)
        voice_prompt = speech_to_text(
            language="en-IN",
            start_prompt="🎙️ TAP TO SPEAK — auto-sends",
            stop_prompt="⏹ LISTENING…",
            just_once=True,
            use_container_width=True,
            key="jarvis_voice_input",
        )

        st.markdown('<div class="input-bar">', unsafe_allow_html=True)
        with st.container(border=False):
            c_in, c_send = st.columns([5, 1], gap="small")
            with c_in:
                prompt = st.text_input("Ask JARVIS anything...", value="" if st.session_state.get("clear_input_flag") else st.session_state.ai_prompt_input, key="ai_prompt_input", label_visibility="collapsed", placeholder="Ask anything...")
            with c_send:
                sent = st.button("➤", key="ai_send_btn", type="primary", use_container_width=True)
        st.markdown("</div>", unsafe_allow_html=True)

    with side_col:
        # Live Intelligence Feed
        st.markdown('<div class="hud-panel"><div class="hud-title">Live Intelligence Feed ● LIVE</div>', unsafe_allow_html=True)
        for dot, text, kind in [
            ("#00d4ff", "Design review with product team...", "INFO"),
            ("#ffb300", "2 tasks overdue — Polish voc…", "WARN"),
            ("#00ff88", "3 pull requests awaiting review", "TIP"),
            ("#ffb300", "Deep-work block 2-4 PM. Noti…", "TIP"),
            ("#00ff88", "CPU usage at 15% — System load nominal", "LIVE"),
        ]:
            st.markdown(f'<div class="feed-item"><span class="feed-dot" style="background:{dot};box-shadow:0 0 8px {dot};"></span><span>{text} <b style="color:{dot};font-size:11px;">{kind}</b></span></div>', unsafe_allow_html=True)
        st.markdown('</div>', unsafe_allow_html=True)

        # Video panel (YouTube) — expandable
        st.markdown('<div class="hud-panel"><div class="hud-title">Video — News / YouTube ⤢</div>', unsafe_allow_html=True)
        v_url = st.session_state.video_url or ""
        if v_url:
            import re as _re
            m = _re.search(r"(?:v=|youtu\.be/|/shorts/)([A-Za-z0-9_-]{6,})", v_url)
            vid = m.group(1) if m else ""
            if vid:
                if st.session_state.video_big:
                    components.html(f'<iframe width="100%" height="420" src="https://www.youtube.com/embed/{vid}?autoplay=1" frameborder="0" allow="autoplay; encrypted-media" allowfullscreen></iframe>', height=440)
                else:
                    components.html(f'<iframe width="100%" height="220" src="https://www.youtube.com/embed/{vid}" frameborder="0" allowfullscreen></iframe>', height=240)
            else:
                st.caption("Video link captured above.")
        else:
            st.caption("Ask for news/video — YouTube plays here.")
        if st.button("⤢ Expand Video", key="video_expand", use_container_width=True):
            st.session_state.video_big = not st.session_state.video_big
            st.rerun()
        st.markdown('</div>', unsafe_allow_html=True)

        # Music terminal (Spotify)
        st.markdown('<div class="hud-panel"><div class="hud-title">Music Terminal — Spotify ⤢</div>', unsafe_allow_html=True)
        m_url = st.session_state.music_url or ""
        if "open.spotify.com" in m_url:
            mm = _re.search(r"(track|playlist|album)/([A-Za-z0-9]+)", m_url)
            if mm:
                kind, mid = mm.group(1), mm.group(2)
                h = 420 if st.session_state.music_big else 180
                components.html(f'<iframe width="100%" height="{h}" src="https://open.spotify.com/embed/{kind}/{mid}" frameborder="0" allow="autoplay; clipboard-write; encrypted-media; fullscreen"></iframe>', height=h+20)
            else:
                st.caption("Spotify link captured above.")
        elif m_url:
            mm = _re.search(r"(?:v=|youtu\.be/|/shorts/)([A-Za-z0-9_-]{6,})", m_url)
            if mm:
                vid = mm.group(1)
                h = 420 if st.session_state.music_big else 180
                components.html(f'<iframe width="100%" height="{h}" src="https://www.youtube.com/embed/{vid}?autoplay=1" frameborder="0" allowfullscreen></iframe>', height=h+20)
            else:
                st.caption("Music link captured above.")
        else:
            st.caption("Ask for songs — plays here.")
        if st.button("⤢ Expand Music", key="music_expand", use_container_width=True):
            st.session_state.music_big = not st.session_state.music_big
            st.rerun()
        st.markdown('</div>', unsafe_allow_html=True)

        st.markdown('<div class="jarvis-camera-panel"><h3>◉ Camera — Vision</h3>', unsafe_allow_html=True)
        camera_image = st.camera_input(
            "Take photo",
            key="ai_camera_input",
            help="Point at any object, capture, then SEND.",
            label_visibility="collapsed",
        )
        st.markdown('</div>', unsafe_allow_html=True)

    all_uploads = list(uploads or []) + ([camera_image] if camera_image is not None else [])
    image_parts = make_image_parts(all_uploads)

    voice_auto_send = False
    if voice_prompt and not prompt:
        prompt = voice_prompt
        # Do NOT assign to st.session_state['ai_prompt_input'] here — widget already instantiated
        st.session_state.jarvis_wave_mode = "listening"
        voice_auto_send = True

    if sent or voice_auto_send:
        prompt = (st.session_state.get("ai_prompt_input") or prompt or "").strip()
        effective_model = FAST_MODEL if use_fast else model
        effective_temp = 0.3 if use_fast else temperature
        effective_tokens = min(max_tokens, 1024) if use_fast else max_tokens

        has_image = bool(image_parts)
        if not prompt and not has_image:
            st.warning("Type a message first.")
        else:
            st.session_state.clear_input_flag = True
            send_prompt = "Describe what is in this attached photo." if (has_image and not prompt) else prompt

            if has_image:
                effective_temp = min(effective_temp, 0.2)
                effective_tokens = max(effective_tokens, 8192)

            with st.chat_message("user"):
                st.markdown(send_prompt)
            st.session_state.ai_messages.append({"role": "user", "content": send_prompt})
            api_messages = build_messages(st.session_state.ai_messages[:-1], send_prompt, image_parts if image_parts else [])

            # Fallback chain: try each model until one returns a response
            FALLBACKS = ["nvidia/nemotron-3.5-super-vl:free", "stealth/crouton-alpha", "xingchen-agi/xing4.0-29b-a4b:free", "recursive/flint-v1.0:free"]
            reply = None
            err = None
            for m in ([effective_model] + [f for f in FALLBACKS if f != effective_model]):
                reply_try, err_try = call_openrouter(api_key, m, api_messages, effective_temp, effective_tokens)
                if not err_try and reply_try and reply_try.strip() and reply_try.strip() != "None":
                    reply = reply_try
                    err = None
                    break
                err = err_try
                reply = reply_try

            with st.chat_message("assistant"):
                with st.spinner("JARVIS is thinking..."):
                    if err:
                        st.error(f"⚠️ {err}")
                        st.info("💡 All free models failed. Check your API key at openrouter.ai/keys or try again.")
                    else:
                        display_reply = reply or "I didn't get a clear response. Try again."
                        import re as _re2
                        vm = _re2.search(r"\[VIDEO:\s*(https?://[^\]\s]+)", display_reply)
                        if vm:
                            st.session_state.video_url = vm.group(1).strip()
                            display_reply = _re2.sub(r"\[VIDEO:\s*https?://[^\]]+\]", "", display_reply).strip()
                        mm2 = _re2.search(r"\[MUSIC:\s*(https?://[^\]\s]+)", display_reply)
                        if mm2:
                            st.session_state.music_url = mm2.group(1).strip()
                            display_reply = _re2.sub(r"\[MUSIC:\s*https?://[^\]]+\]", "", display_reply).strip()
                        # Auto-detect bare YouTube / Spotify URLs in normal text
                        yt = _re2.search(r"https?://(?:www\.)?(?:youtube\.com/watch\?v=|youtu\.be/)([A-Za-z0-9_-]{6,})", display_reply)
                        if yt and not st.session_state.video_url:
                            st.session_state.video_url = yt.group(0)
                        sp = _re2.search(r"https?://open\.spotify\.com/[^\s\]]+", display_reply)
                        if sp and not st.session_state.music_url:
                            st.session_state.music_url = sp.group(0)
                        st.session_state.ai_messages.append({"role": "assistant", "content": display_reply})
                        if use_voice:
                            st.session_state.jarvis_wave_mode = "speaking"
                            try:
                                speak_text = clean_tts_text(display_reply)
                                audio = synthesize_speech(speak_text, voice=voice_choice, rate=f"+{voice_speed-100}%")
                                audio_b64 = base64.b64encode(audio).decode("ascii")
                                components.html(speak_print_html(speak_text, audio_b64), height=340)
                            except Exception as ve:
                                st.warning(f"Voice unavailable: {ve}")
                                st.markdown(display_reply)
                        else:
                            st.markdown(display_reply)
        st.rerun()


if __name__ == "__main__":
    main()
