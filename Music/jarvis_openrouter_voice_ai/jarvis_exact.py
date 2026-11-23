from __future__ import annotations
import asyncio, base64, os, re, tempfile, time, queue, threading
from pathlib import Path
from typing import Any
import requests, streamlit as st, streamlit.components.v1 as components
import numpy as np
try:
    import sounddevice as sd
except Exception:
    sd = None  # cloud / phones don't need the host mic
import speech_recognition as sr
from dotenv import load_dotenv

try:
    import memory_engine as mem
except Exception:
    mem = None
try:
    import web_engine as webx
except Exception:
    webx = None

APP_DIR = Path(__file__).resolve().parent
API_URL = "https://openrouter.ai/api/v1/chat/completions"
ENV_FILE = APP_DIR / ".env"
load_dotenv(ENV_FILE)

def _bg_data_uri() -> str:
    try:
        p = Path("C:/Users/RAMULUREDDY/Downloads/jarvis_background.png")
        if p.exists():
            b = base64.b64encode(p.read_bytes()).decode()
            return f"data:image/png;base64,{b}"
        txt = APP_DIR / "jarvis_bg_b64.txt"
        if txt.exists():
            return f"data:image/png;base64,{txt.read_text(encoding='utf-8').strip()}"
    except Exception:
        pass
    return ""

SYSTEM_PROMPT = """You are JARVIS, Iron Man AI OS assistant. Answer SHORT, BRIEF and HIGH-PRECISION — match answer length to question. Greetings need 1 line, definitions 2-4 lines, factual questions 2-6 lines. Only go long (10+ lines, stories, lists) if the user explicitly asks for details, a story, or a breakdown. Never ramble, never add filler, never parrot the question.
Web search results are provided in the user message under "Web results:" — if present, use them for current facts ONLY when relevant (cite Title — URL + today's date). If web results are irrelevant or stale, ignore them and answer from knowledge. If you truly don't know, say so in 1 line — don't guess.
When user asks for news/video/movie/film, return [VIDEO: https://www.youtube.com/watch?v=...] with a real YouTube link. Only playback when explicitly asked to play — no refusals.
When user asks for songs (play/music/song/spotify/track/listen — ANY song request), you MUST include [MUSIC: https://open.spotify.com/track/<22-char-ID>] if you know a valid ID, else reply briefly and the app will find the track. Full songs play via YouTube — no 30-second previews.
CRITICAL: plain, accurate answers. Never invent facts, never say "I cannot browse". Never use the phrase "functioning at optimal capacity" or similar boilerplate.
"""

VISION_PROMPT = """You are JARVIS with camera vision. Describe ONLY what is actually visible in the image — never invent details.
1) OCR: transcribe ALL readable text exactly as shown, line by line. If no text, say "No readable text".
2) Then list: Person (age range/gender/expression if present, else "No person"), Objects (every distinct object), Focus (sharpest area), Lighting/Setting.
3) News check: If OCR/headline mentions real names/dates, verify with web search and give only confirmed facts with source + date. If you cannot verify, give no news.
Keep it factual and specific. Say "Not visible" for anything you cannot see.
User question: """

MODELS = ["google/gemma-4-31b-it","nvidia/nemotron-3.5-super-vl:free","xingchen-agi/xing4.0-29b-a4b:free","recursive/flint-v1.0:free","meta/muse-ember"]
LABELS = {"google/gemma-4-31b-it":"Gemma 4 31B IT (default)","nvidia/nemotron-3.5-super-vl:free":"Nemotron 3.5 Super VL (free)","xingchen-agi/xing4.0-29b-a4b:free":"Xing4.0 29B A4B (free)","recursive/flint-v1.0:free":"Flint (free)","meta/muse-ember":"Muse Ember"}
DEFAULT = MODELS[0]
FAST = MODELS[1]

def valid_key(k): return (k or "").strip().startswith("sk-or-v1-") and len((k or "").strip())>20
def persist_key(k): ENV_FILE.write_text(f"OPENROUTER_API_KEY={k}\n", encoding="utf-8")
_JARVIS_API_KEY: str = ""


def _server_key_from_env_file() -> str:
    """Read the locally-saved OpenRouter key from the git-ignored .env (server-side only)."""
    try:
        if not ENV_FILE.exists():
            return ""
        for _l in ENV_FILE.read_text(encoding="utf-8").splitlines():
            _l = _l.strip()
            if _l.startswith("OPENROUTER_API_KEY="):
                _v = _l.split("=", 1)[1].strip().strip('"').strip("'").strip()
                if valid_key(_v):
                    return _v
    except Exception:
        pass
    return ""


def get_key() -> str:
    """Return the OpenRouter API key from SERVER-SIDE sources only.

    Priority: cloud env var (Streamlit secret) -> local env file. The key is
    never sourced from st.session_state (client-adjacent state) and is never
    written into HTML/JS or HTTP bodies. Local saves persist to the git-ignored
    .env on the host.
    """
    global _JARVIS_API_KEY
    if _JARVIS_API_KEY:
        return _JARVIS_API_KEY
    _k = ""
    try:
        _sec = st.secrets.get("OPENROUTER_API_KEY", "")
        if valid_key(_sec):
            _k = _sec.strip()
    except Exception:
        _k = ""
    if not _k:
        _e = os.getenv("OPENROUTER_API_KEY", "").strip()
        if valid_key(_e):
            _k = _e
    if not _k:
        _k = _server_key_from_env_file()
    if _k:
        _JARVIS_API_KEY = _k
    return _k


_CCV2_REGISTRY: dict = {}


def _ccv2_component(name: str, html: str, js: str):
    """Register a CCv2 component once per process using a plain dict.

    Deliberately NOT wrapped in @st.cache_resource: Streamlit's cache calls
    inspect.getsource() on the function, and this module's large embedded
    CSS/JS strings trip the CPython 3.13 tokenizer. A plain registry avoids
    inspect entirely and still registers each component only once.
    """
    _REG = getattr(st, "_jarvis_ccv2_registry", None)
    if _REG is None:
        _REG = {}
        try:
            setattr(st, "_jarvis_ccv2_registry", _REG)
        except Exception:
            pass
    comp = _REG.get(name)
    if comp is None:
        comp = st.components.v2.component(name, html=html, js=js)
        _REG[name] = comp
    return comp

# =====================================================================
# ALWAYS-ON JARVIS VOICE PIPELINE
# - Mic stays ON via background sounddevice capture (no button needed)
# - Adaptive noise gate + energy-based VAD (noise cancellation / silence handling)
# - Wake word ("Jarvis") OR clap/snap (energy spike) -> transitions to listening
# - Finalized utterance -> Google STT -> command -> _CMD_Q -> chat flow
# - Misheard twice -> JARVIS asks for clarification
# - After idle silence while listening -> back to sleep mode
# =====================================================================
_JARVIS_STATE = {"state": "sleeping"}
_JARVIS_ASK_ME = {"text": ""}
_CMD_Q: queue.Queue = queue.Queue()
_UTT_Q: queue.Queue = queue.Queue()
_VOICE_STOP_EVENT = threading.Event()
_VOICE_THREAD = None
_VOICE_BUF: list = []
_VOICE_SILENCE_START = None
_VOICE_NOISE_EMA = 0.005
_VOICE_LAST_ACTIVITY_T = 0.0
_VOICE_FAIL_COUNT = 0
_VOICE_CLAP = False
_WAKE_RE = re.compile(r"\bjarvis\b", re.IGNORECASE)
_JARVIS_IDLE_SLEEP_S = 86400.0  # 24h — effectively "always listening" (user asked to keep JARVIS always active)
_VOICE_VAD_GAP_S = 1.2  # slightly longer VAD silence gap to avoid cutting utterances too early
_VOICE_RATE = 16000
_VOICE_VAD_GAP_S = 0.9


def _rms(x) -> float:
    a = np.asarray(x, dtype=np.float32)
    if a.size == 0:
        return 0.0
    return float(np.sqrt(float(np.mean(a * a))))


def _voice_on_audio(indata, frames, time_info, status):
    global _VOICE_BUF, _VOICE_SILENCE_START, _VOICE_NOISE_EMA, _VOICE_CLAP
    try:
        x = np.asarray(indata, dtype=np.float32).reshape(-1)
        if x.size == 0:
            return
        rms = _rms(x)
        # adaptive noise floor (EMA) + noise gate: speech must stand above gate
        _VOICE_NOISE_EMA = max(rms * 0.05, _VOICE_NOISE_EMA * 0.90 + rms * 0.10)
        gate = max(0.002, _VOICE_NOISE_EMA * 2.5)
        now = time.monotonic()
        if rms > gate:
            _VOICE_BUF.extend(x.tolist())
            _VOICE_SILENCE_START = None
            if rms > max(0.008, _VOICE_NOISE_EMA * 5.0):
                _VOICE_CLAP = True
        else:
            if not _VOICE_BUF:
                return
            if _VOICE_SILENCE_START is None:
                _VOICE_SILENCE_START = now
            elif now - _VOICE_SILENCE_START > _VOICE_VAD_GAP_S:
                buf = _VOICE_BUF
                _dur = len(buf) / _VOICE_RATE
                _VOICE_BUF = []
                _VOICE_SILENCE_START = None
                if _dur < 0.25:
                    return
                arr = np.asarray(buf, dtype=np.float32)
                pcm = (arr * 32767.0).astype(np.int16).tobytes()
                _UTT_Q.put(pcm)
    except Exception:
        pass


def _voice_handle_transcript(t: str, conf) -> None:
    global _VOICE_FAIL_COUNT, _VOICE_CLAP, _VOICE_LAST_ACTIVITY_T
    if _JARVIS_STATE["state"] == "sleeping":
        clap = _VOICE_CLAP
        _VOICE_CLAP = False
        _wake_hit = bool(clap) or bool(_WAKE_RE.search(t or ""))
        if not _wake_hit:
            _tl = (t or "").lower()
            if "jarvis" in _tl:
                _wake_hit = True
        if not _wake_hit:
            return
        cmd = _WAKE_RE.sub(" ", t or "").strip()
        if not cmd:
            cmd = (t or "").strip()
        _JARVIS_STATE["state"] = "listening"
        _VOICE_LAST_ACTIVITY_T = time.monotonic()
        if cmd:
            _CMD_Q.put(cmd)
        return
    # listening: transcript (minus wake word handled above) is the command
    _has_cmd = bool((t or "").strip())
    if _has_cmd:
        _CMD_Q.put((t or "").strip())
        _VOICE_LAST_ACTIVITY_T = time.monotonic()
    try:
        if _has_cmd and conf is not None and float(conf) < 0.45:
            _VOICE_FAIL_COUNT += 1
            if _VOICE_FAIL_COUNT >= 2:
                _VOICE_FAIL_COUNT = 0
                _JARVIS_ASK_ME["text"] = "Sorry, I did not catch that clearly, sir. Could you repeat your question?"
    except Exception:
        pass


def _voice_stt_worker() -> None:
    r = sr.Recognizer()
    while True:
        try:
            pcm = _UTT_Q.get(timeout=5)
        except queue.Empty:
            continue
        if _VOICE_STOP_EVENT.is_set():
            return
        t, conf = "", 0.0
        try:
            resp = r.recognize_google(sr.AudioData(pcm, _VOICE_RATE, 2), language="en-US")
            t = (resp.get("transcript") or "").strip()
            conf = float(resp.get("confidence") or 0.0)
        except Exception:
            t, conf = "", 0.0
        _voice_handle_transcript(t, conf)


def _voice_capture_loop() -> None:
    try:
        with sd.InputStream(samplerate=_VOICE_RATE, channels=1, dtype="float32", callback=_voice_on_audio) as stream:
            while not _VOICE_STOP_EVENT.wait(0.25):
                if _JARVIS_STATE["state"] == "listening" and (time.monotonic() - _VOICE_LAST_ACTIVITY_T) > _JARVIS_IDLE_SLEEP_S:
                    _JARVIS_STATE["state"] = "sleeping"
    except Exception as e:
        print("JARVIS voice capture error:", e)
    finally:
        try:
            _VOICE_STOP_EVENT.clear()
        except Exception:
            pass


def _ensure_voice_listener() -> None:
    global _VOICE_THREAD
    if sd is None:
        return
    if _VOICE_THREAD is None or not _VOICE_THREAD.is_alive():
        _VOICE_THREAD = threading.Thread(target=_voice_capture_loop, daemon=True, name="jarvis-voice-listener")
        _VOICE_THREAD.start()

def search_youtube(topic):
    import urllib.parse as up
    candidates = []
    # Clean noisy queries: "play random movie" -> "random movie trailer official"
    _t = (topic or "").strip()
    _lt = _t.lower().strip()
    for _w in ["play ", "please ", "show ", "show me ", "watch "]:
        if _lt.startswith(_w):
            _t = _t[len(_w):].strip()
            break
    if "random movie" in _lt or _lt in ("random movie", "movie"):
        _t = "random movie trailer official"
    elif "movie" in _lt or "film" in _lt or "video" in _lt or "trailer" in _lt:
        if "trailer" not in _lt:
            _t = f"{_t} trailer official"
    if not _t:
        _t = topic or ""
    # 1) Direct YouTube results scrape first (DDG is captcha-blocked from this region) — fast timeout for <3s replies
    try:
        q = up.quote_plus(_t)
        r2 = requests.get(f"https://www.youtube.com/results?search_query={q}", headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36", "Accept-Language": "en-US,en;q=0.9"}, timeout=4)
        raw = r2.text if r2.status_code == 200 else ""
        for vid in re.findall(r'"videoId"\s*:\s*"([A-Za-z0-9_-]{11})"', raw):
            url = f"https://www.youtube.com/watch?v={vid}"
            if url not in candidates:
                candidates.append(url)
            if len(candidates) >= 8:
                break
        if len(candidates) < 4:
            for vid in re.findall(r'/watch\?v=([A-Za-z0-9_-]{11})', raw):
                url = f"https://www.youtube.com/watch?v={vid}"
                if url not in candidates:
                    candidates.append(url)
                if len(candidates) >= 8:
                    break
    except Exception:
        pass
    # 2) DuckDuckGo fallback only if direct scrape found nothing
    if not candidates:
        try:
            r=requests.get("https://html.duckduckgo.com/html/",params={"q":f"site:youtube.com {_t}"},headers={"User-Agent":"Mozilla/5.0"},timeout=4)
            for h in re.findall(r'href="([^"]+)"', r.text):
                if "youtube.com/watch" in h:
                    if h.startswith("//"): h="https:"+h
                    elif "uddg=" in h: h=up.unquote(up.parse_qs(up.urlparse(h).query).get("uddg",[""])[0])
                    if "youtube.com/watch" in h and h not in candidates:
                        candidates.append(h)
                if len(candidates) >= 6:
                    break
        except Exception:
            pass
    # Validate only first 2 candidates (fast <3s) — NEVER return unvalidated ID.
    for url in candidates[:3]:
        try:
            o = requests.get("https://www.youtube.com/oembed", params={"url": url, "format": "json"}, timeout=5)
            if o.status_code == 200:
                return url
        except Exception:
            continue
    return ""

def is_info_query(q: str) -> bool:
    import re as _re
    t = (q or "").lower().strip()
    if not t:
        return False
    # Casual / conversational turns — never web-search these
    if _re.search(r"\b(how are you|how r u|how r you|what'?s up|sup|hi|hello|hey|good morning|good evening|good night|thanks|thank you|cool|nice|ok|okay|bye|yes|no|hmm|wow)\b", t):
        return False
    if len(t.split()) <= 2 and not _re.search(r"\b(who|what|when|where|why|which|how many|how much|price|weather|news|today|latest|score|match|date|time)\b", t):
        return False
    # Information questions
    return bool(_re.search(r"\b(who|what|when|where|why|which|whose|how|did|does|will|can|should|is|are|explain|define|meaning of|tell me|give me|describe|summary|history|capital|president|founder|population|height|weight|recipe|price|cost|weather|forecast|news|latest|today|current|recent|score|match|kabaddi|election|stock|btc|usd)\b", t))


def search_web(topic: str, max_results: int = 4) -> str:
    """Fast web search (Bing RSS, no key, ~1s). Only returns RELEVANT results: requires a query token in the title;
    returns '' when nothing relevant is found so the model answers from its own knowledge rather than junk context."""
    import urllib.parse as _up3
    q = (topic or "").strip()
    if not q:
        return ""
    from datetime import datetime
    today = datetime.now().strftime("%Y-%m-%d")
    is_news = any(k in q.lower() for k in ("news", "today", "latest", "recent", "update", "score", "match", "weather"))
    # Unquoted query (Bing returns WhatsApp spam for quoted phrases from this IP) — do NOT quote
    qq_raw = f"{q} {datetime.now().strftime('%Y-%m')}" if is_news else q
    STOP = {"what", "who", "where", "when", "why", "how", "the", "today", "latest", "recent", "news", "about", "with", "from", "that", "this", "answer", "give", "tell", "explain"}
    tokens = [t for t in re.findall(r"[a-zA-Z0-9]+", q.lower()) if len(t) >= 4 and t not in STOP]
    try:
        r = requests.get(f"https://www.bing.com/search?format=rss&q={_up3.quote_plus(qq_raw)}", headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36"}, timeout=2)
        if r.status_code != 200 or not r.text:
            r = None
        items = re.findall(r"<item>.*?</item>", r.text, re.DOTALL) if r is not None else []
        lines = []
        junk_markers = ("whatsapp", "scribd.com", "merohealthline.com", "deviantart.com", "answer.microsoft.com", "wa.link", "wa.me")
        for it in items:
            if len(lines) >= max_results:
                break
            t = re.search(r"<title>(.*?)</title>", it, re.DOTALL)
            l = re.search(r"<link>(.*?)</link>", it)
            d = re.search(r"<description>(.*?)</description>", it, re.DOTALL)
            title = re.sub(r"[^\x20-\x7E]", " ", re.sub(r"\s+", " ", (t.group(1) if t else "").replace("<![CDATA[", "").replace("]]>", "")).strip())
            link = (l.group(1) if l else "").strip()
            desc = re.sub(r"<[^>]+>", " ", (d.group(1) if d else "").replace("<![CDATA[", "").replace("]]>", ""))
            desc = re.sub(r"\s+", " ", desc).strip()[:180]
            desc = re.sub(r"[^\x20-\x7E]", " ", desc)
            desc = re.sub(r"\s+", " ", desc).strip()
            tl = title.lower()
            if any(j in (tl + " " + link.lower()) for j in junk_markers):
                continue
            if not title or len(title) < 5:
                continue
            # Relevance: title must contain at least one query token (if tokens exist)
            if tokens and not any(re.search(rf"\b{re.escape(tok)}\b", tl) for tok in tokens):
                continue
            lines.append(f"- {title} — {desc} ({link})" if desc and desc != title else f"- {title} ({link})")
        if lines:
            return f"Web results for '{q}' ({today}):\n" + "\n".join(lines)
    except Exception:
        pass
    # News fallback: Google News RSS is fast (~1.5s) and reliably current when Bing RSS is empty/blocked.
    if is_news:
        try:
            gn = requests.get(
                "https://news.google.com/rss/search?q=" + _up3.quote_plus(q) + "&hl=en-US&gl=US&ceid=US:en",
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36"},
                timeout=4,
            )
            if gn.status_code == 200:
                glines = []
                for it in re.findall(r"<item>.*?</item>", gn.text, re.DOTALL)[:max_results]:
                    t = re.search(r"<title>(.*?)</title>", it, re.DOTALL)
                    d = re.search(r"<pubDate>(.*?)</pubDate>", it, re.DOTALL)
                    l = re.search(r"<link>(.*?)</link>", it, re.DOTALL)
                    title = re.sub(r"\s+", " ", (t.group(1) if t else "").replace("<![CDATA[", "").replace("]]>", "")).strip()
                    if not title:
                        continue
                    when = (d.group(1) if d else "").strip()[:22]
                    link = (l.group(1) if l else "").strip()
                    glines.append(f"- {title} ({when}) {link}")
                if glines:
                    return f"Latest news for '{q}' ({today}):\n" + "\n".join(glines)
        except Exception:
            pass
    return ""


def desktop_web_lookup(topic: str) -> str:
    """Local scraper first, legacy RSS fallback second."""
    try:
        if webx:
            d = webx.get_context(topic, deep=False, budget=6.5)
            if d and d.get("context"):
                return d["context"]
    except Exception:
        pass
    return search_web(topic)


# Spotify track IDs verified live via oEmbed (2026-11). Unverified/fake IDs are NOT kept here:
# a wrong ID renders "Page not found" in the desktop Spotify panel. Desktop playback prefers
# full-song YouTube audio anyway; this table is only a fast Spotify fallback.
KNOWN_TRACKS = {
    "blinding lights": "0VjIjW4GlUZAMYd2vXMi3b",
    "despacito": "6habFhsOp2NvshLv26DqMb",
    "someone like you": "1zwMYTA5nlNjZxYrvBB2pV",
}

def clean_music_query(prompt: str) -> str:
    q = (prompt or "").strip().lower()
    import re as _re
    q = _re.sub(r"[\"“”‘’`]", " ", q)
    # Drop intent words so search is "shape of you ed sheeran" not "play shape of you song"
    for w in ["please", "play", "playing", "put on", "put", "on", "song", "songs", "music", "spotify", "track", "listen", "to", "some", "latest", "a", "an", "the"]:
        q = re.sub(rf"\b{re.escape(w)}\b", " ", q)
    q = re.sub(r"\s+", " ", q).strip(" ,.!?\"")
    return q or (prompt or "").strip()

def _known_track_for(query: str) -> str:
    q = (query or "").lower().strip()
    if not q:
        return ""
    # Exact substring (longest key wins)
    best, best_len = "", 0
    for k, tid in KNOWN_TRACKS.items():
        if k in q and len(k) > best_len:
            best, best_len = k, len(k)
    if best and len(KNOWN_TRACKS[best]) == 22:
        return f"https://open.spotify.com/track/{KNOWN_TRACKS[best]}"
    # Fuzzy / typo-tolerant: "beliver" -> "believer", "shape ov you" -> "shape of you"
    import difflib
    keys = list(KNOWN_TRACKS.keys())
    # Try whole-query close match, then per-token close match
    close = difflib.get_close_matches(q, keys, n=1, cutoff=0.65)
    if not close:
        for tok in q.split():
            close = difflib.get_close_matches(tok, keys, n=1, cutoff=0.65)
            if close:
                break
            # Multi-word keys with one typo token: compare each token to each key token
            for k in keys:
                for kw in k.split():
                    if difflib.SequenceMatcher(None, tok, kw).ratio() >= 0.75 and len(tok) >= 3:
                        close = [k]
                        break
                if close:
                    break
            if close:
                break
    if close and len(KNOWN_TRACKS[close[0]]) == 22:
        return f"https://open.spotify.com/track/{KNOWN_TRACKS[close[0]]}"
    return ""

def search_spotify(topic):
    import urllib.parse as up
    candidates = []
    q = clean_music_query(topic)
    search_q = f"{q} spotify track"
    # 1) Known fast path — validate via oEmbed before returning (a wrong hardcoded ID showed "Page not found")
    known = _known_track_for(q)
    if known:
        for _attempt in (8, 5):
            try:
                o = requests.get("https://open.spotify.com/oembed", params={"url": known}, timeout=_attempt)
                if o.status_code == 200:
                    return known
                if o.status_code == 404:
                    break
            except Exception:
                continue
        # 404 / unreachable -> fall through to search below; NEVER return the unvalidated ID
        known = ""
    # 2) DuckDuckGo lite + html (lite is friendlier to bots)
    for endpoint, params in [
        ("https://lite.duckduckgo.com/lite/", {"q": f"site:open.spotify.com/track {search_q}"}),
        ("https://html.duckduckgo.com/html/", {"q": f"site:open.spotify.com/track {search_q}"}),
    ]:
        try:
            r = requests.get(endpoint, params=params, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36"}, timeout=10)
            raw = r.text if r.status_code == 200 else ""
            for h in re.findall(r'href="([^"]+)"', raw):
                cand = h
                if h.startswith("//"):
                    cand = "https:" + h
                elif "uddg=" in h:
                    try:
                        cand = up.unquote(up.parse_qs(up.urlparse(h).query).get("uddg", [""])[0])
                    except Exception:
                        cand = h
                for m in re.finditer(r"/track/([A-Za-z0-9]{22})", cand):
                    clean = f"https://open.spotify.com/track/{m.group(1)}"
                    if clean not in candidates:
                        candidates.append(clean)
                # Also try plain text URLs embedded in page
                if len(candidates) >= 8:
                    break
            for m in re.finditer(r"open\.spotify\.com/track/([A-Za-z0-9]{22})", raw):
                clean = f"https://open.spotify.com/track/{m.group(1)}"
                if clean not in candidates:
                    candidates.append(clean)
            if len(candidates) >= 8:
                break
        except Exception:
            continue
    # 2b) Bing fallback when DDG is bot-blocked/new-captcha
    if not candidates:
        try:
            import urllib.parse as _up2
            _bq = _up2.quote_plus(f'"open.spotify.com/track" {search_q}')
            _br = requests.get(f"https://www.bing.com/search?q={_bq}", headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36", "Accept-Language": "en-US,en;q=0.9"}, timeout=10)
            _braw = _br.text if _br.status_code == 200 else ""
            for m in re.finditer(r"open\.spotify\.com/track/([A-Za-z0-9]{22})", _braw):
                _clean = f"https://open.spotify.com/track/{m.group(1)}"
                if _clean not in candidates:
                    candidates.append(_clean)
                if len(candidates) >= 8:
                    break
        except Exception:
            pass
    # Validate only first 3 candidates (fast <3s) — skip dead tracks, NEVER return unvalidated ID
    for url in candidates[:3]:
        try:
            o = requests.get("https://open.spotify.com/oembed", params={"url": url}, timeout=2)
            if o.status_code == 200:
                return url
        except Exception:
            continue
    return ""


def get_spotify_meta(url: str) -> dict:
    try:
        o = requests.get("https://open.spotify.com/oembed", params={"url": url}, timeout=8)
        if o.status_code == 200:
            d = o.json()
            return {"title": d.get("title", ""), "author": d.get("author_name", ""), "thumb": d.get("thumbnail_url", "")}
    except Exception:
        pass
    return {}


def _song_title_from_query(query: str) -> str:
    """'shape of you' -> 'Shape Of You' (keeps small words lowercase)."""
    q = re.sub(r"\s+", " ", (query or "").strip())
    if not q:
        return "Your Song"
    small = {"a", "an", "the", "of", "in", "on", "at", "to", "and", "or", "for", "with", "from", "by"}
    words = []
    for i, w in enumerate(q.split()):
        words.append(w if (i > 0 and w.lower() in small) else w[:1].upper() + w[1:])
    return " ".join(words)


@st.cache_data(ttl=86400, show_spinner=False)
def itunes_song_meta(query: str) -> dict:
    """Free iTunes lookup: exact song title, artist, album art and a 30s preview.
    Used by the mobile Media card; never blocks the reply path (cached page render only)."""
    q = (query or "").strip()
    if not q:
        return {}
    try:
        r = requests.get(
            "https://itunes.apple.com/search",
            params={"term": q, "entity": "song", "limit": 3},
            timeout=6,
        )
        if r.status_code != 200:
            return {}
        for item in (r.json().get("results") or []):
            preview = (item.get("previewUrl") or "").strip()
            if not preview:
                continue
            art = (item.get("artworkUrl100") or "").replace("100x100", "300x300")
            return {
                "title": (item.get("trackName") or "").strip(),
                "artist": (item.get("artistName") or "").strip(),
                "art": art,
                "preview": preview,
                "apple_url": (item.get("trackViewUrl") or "").strip(),
            }
    except Exception:
        pass
    return {}


LAYOUT_FILE = APP_DIR / "layout.json"

DEFAULT_LAYOUT = {
    "columns": [1.0, 1.5, 1.0],
    "clock_h": 78,
    "chat_h": 240,
    "reactor_h": 340,
    "left_order": ["clock", "system", "music", "weather"],
    "center_order": ["reactor", "chat"],
    "right_order": ["camera", "video", "tasks"],
    "panel_w_scale": 1.0,
}

def load_layout() -> dict:
    try:
        if LAYOUT_FILE.exists():
            import json as _j
            return _j.loads(LAYOUT_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return dict(DEFAULT_LAYOUT)

def save_layout(cfg: dict) -> None:
    try:
        import json as _j
        LAYOUT_FILE.write_text(_j.dumps(cfg, indent=2), encoding="utf-8")
    except Exception:
        pass

TASKS_FILE = APP_DIR / "tasks.json"

def load_tasks() -> list:
    try:
        if TASKS_FILE.exists():
            import json as _j
            return _j.loads(TASKS_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return [
        {"title": "Complete DSA practice", "time": "02:00 PM", "done": True},
        {"title": "Work on AI project (Jarvis)", "time": "05:00 PM", "done": False},
        {"title": "Revise DBMS", "time": "07:00 PM", "done": False},
        {"title": "Prepare for CIA", "time": "09:00 PM", "done": False},
    ]

def save_tasks(tasks: list) -> None:
    try:
        import json as _j
        TASKS_FILE.write_text(_j.dumps(tasks, indent=2), encoding="utf-8")
    except Exception:
        pass

def get_daily_date() -> str:
    from datetime import date as _d
    return _d.today().isoformat()


USER_PROFILE_FILE = APP_DIR / "user_profile.json"
DEFAULT_USER_PROFILE = {"name": "", "preferences": "", "notes": "", "updated": ""}


def load_user_profile() -> dict:
    import json as _j
    try:
        if USER_PROFILE_FILE.exists():
            d = _j.loads(USER_PROFILE_FILE.read_text(encoding="utf-8"))
            if isinstance(d, dict):
                d.setdefault("name", "")
                d.setdefault("preferences", "")
                d.setdefault("notes", "")
                d.setdefault("updated", "")
                return d
    except Exception:
        pass
    return dict(DEFAULT_USER_PROFILE)


def save_user_profile(p: dict) -> None:
    import json as _j
    try:
        USER_PROFILE_FILE.write_text(_j.dumps(p or {}, indent=2), encoding="utf-8")
        if isinstance(p, dict):
            p["updated"] = get_daily_date()
    except Exception:
        pass


def get_user_context() -> str:
    """Long-term personal context JARVIS remembers between sessions."""
    try:
        p = load_user_profile()
    except Exception:
        p = dict(DEFAULT_USER_PROFILE)
    bits = []
    nm = (p.get("name") or "").strip()
    if nm:
        bits.append(f"The user's name is {nm}.")
    pref = (p.get("preferences") or "").strip()
    if pref:
        bits.append(f"User preferences: {pref}")
    notes = (p.get("notes") or "").strip()
    if notes:
        bits.append(f"User notes: {notes}")
    if not bits:
        return ""
    return "Long-term user context (from memory): " + " ".join(bits) + "."


def update_user_profile(name: str = "", preferences: str = "", notes: str = "") -> dict:
    p = load_user_profile()
    if (name or "").strip():
        p["name"] = name.strip()
        if mem:
            try:
                mem.add_memory(f"The user's name is {name.strip()}.", "identity", 5)
            except Exception:
                pass
    if (preferences or "").strip():
        p["preferences"] = preferences.strip()
        if mem:
            try:
                mem.add_memory(f"The user prefers: {preferences.strip()}", "preference", 4)
            except Exception:
                pass
    if (notes or "").strip():
        p["notes"] = notes.strip()
        if mem:
            try:
                mem.add_memory(f"User note: {notes.strip()}", "fact", 3)
            except Exception:
                pass
    save_user_profile(p)
    return p


def get_full_context(prompt: str = "", include_previous: bool = False) -> str:
    """Profile + auto-learned memories + (on a fresh session) the last conversation."""
    parts = []
    try:
        parts.append(get_user_context())
    except Exception:
        pass
    if mem:
        try:
            parts.append(mem.get_memory_context(prompt))
        except Exception:
            pass
        if include_previous:
            try:
                start = float(st.session_state.get("_session_start") or time.time())
                parts.append(mem.previous_session_context(start, 8))
            except Exception:
                pass
    out = "\n".join(p for p in parts if p)
    return out[:2800]


def _is_correction(prompt: str) -> bool:
    p = (prompt or "").strip().lower()
    return bool(re.match(
        r"^(no\b|nope\b|wrong\b|that'?s wrong\b|that is wrong\b|incorrect\b|actually\b|i meant\b|not true\b)",
        p,
    ))


def _annotations_to_sources(msg: dict) -> list[dict]:
    out, seen = [], set()
    try:
        for a in (msg.get("annotations") or []):
            if not isinstance(a, dict) or a.get("type") != "url_citation":
                continue
            uc = a.get("url_citation") or {}
            url = (uc.get("url") or "").strip()
            title = re.sub(r"\s+", " ", (uc.get("title") or url)).strip()[:180]
            if not url or url in seen:
                continue
            seen.add(url)
            out.append({"title": title, "url": url, "source": "web"})
    except Exception:
        pass
    return out


def call_or_online(api_key, model, messages, temp=0.2, toks=900):
    """OpenRouter web plugin call: real web search + page reading + citations.

    Returns (reply, error, sources). This is the guaranteed-knowledge fallback when
    the local scraper finds nothing useful.
    """
    if not api_key:
        return None, "No API key", []
    models = []
    for m in (model, DEFAULT, "google/gemma-4-31b-it"):
        om = m if m.endswith(":online") else f"{m}:online"
        if om not in models:
            models.append(om)
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "X-OpenRouter-Title": "JARVIS AI",
        "HTTP-Referer": "https://openrouter.ai/",
    }
    last_err = "Web search failed"
    for m in models:
        try:
            payload = {
                "model": m,
                "messages": messages,
                "temperature": temp,
                "max_tokens": max(int(toks), 400),
                "stream": False,
            }
            resp = requests.post(API_URL, headers=headers, json=payload, timeout=45)
            if not resp.ok:
                try:
                    detail = resp.json().get("error", {}).get("message", resp.text)
                except Exception:
                    detail = resp.text
                last_err = f"Web plugin error ({resp.status_code}): {detail}"
                continue
            data = resp.json()
            ch = data.get("choices") or []
            if not ch:
                last_err = "No choices from web plugin"
                continue
            msg = ch[0].get("message", {}) or {}
            content = (msg.get("content") or "").strip()
            sources = _annotations_to_sources(msg)
            if content and content != "None":
                return content, None, sources
            last_err = "Empty web answer"
        except requests.Timeout:
            last_err = "Web search timed out"
            continue
        except Exception as e:
            last_err = f"Web search error: {e}"
            continue
    return None, last_err, []



def get_weather():
    try:
        r=requests.get("https://api.open-meteo.com/v1/forecast?latitude=12.97&longitude=77.59&current=temperature_2m,relative_humidity_2m,weather_code,windspeed_10m&daily=temperature_2m_max,temperature_2m_min&timezone=Asia%2FKolkata",timeout=10)
        d=r.json(); c=d.get("current",{}); day=d.get("daily",{})
        return {"temp":c.get("temperature_2m",27),"hum":c.get("relative_humidity_2m",72),"wind":c.get("windspeed_10m",11),"code":c.get("weather_code",3),"max":(day.get("temperature_2m_max") or [29])[0],"min":(day.get("temperature_2m_min") or [21])[0]}
    except Exception:
        return {"temp":27,"hum":72,"wind":11,"code":3,"max":29,"min":21}

DOMAIN_PROMPTS = {
    "coding": "You are JARVIS, an elite senior coding copilot. Give precise, actionable code-level answers: short diffs, exact snippets, root-cause reasoning, no filler.",
    "creative": "You are JARVIS, a creative writing partner. Help craft stories, poems, scripts; be imaginative but concise.",
    "research": "You are JARVIS, a research summarizer. Answer with structured, in-depth, sourced summaries and clear breakdowns.",
    "personal": "You are JARVIS, a personal assistant. Tailor advice to the user's life context and goals.",
}
GENERAL_PROMPT = SYSTEM_PROMPT


def detect_domain(prompt: str) -> str:
    """Specialize the answer persona per domain (coding / creative / research / personal / general)."""
    p = (prompt or "").lower()
    words = len(p.split())
    if words < 14 and re.search(r"\b(code|python|javascript|typescript|c\+\+|c#|golang|rust|debug|bug|function|algorithm|sql|api|refactor|compile|error|exception|regex|pytest|django|flask|react|frontend|backend|deploy|docker|kubernetes)\b", p):
        return "coding"
    if words < 14 and re.search(r"\b(story|stories|creative|fiction|poem|poetry|write|writing|novel|script|character|plot|fiction)\b", p):
        return "creative"
    if words < 14 and re.search(r"\b(research|summary|summarize|deep dive|deepdive|analyze|analysis|explain in depth|report|study|compare|evaluate|thesis)\b", p):
        return "research"
    if words < 14 and re.search(r"\b(my|me|personal|life|relationship|friend|family|habit|goal)\b", p):
        return "personal"
    return "general"


_LANG_NAMES = {
    "te": "Telugu (తెలుగు)", "hi": "Hindi (हिन्दी)", "kn": "Kannada (ಕನ್ನಡ)",
    "ta": "Tamil (தமிழ்)", "ml": "Malayalam (മലയാളം)", "mr": "Marathi (मराठी)",
    "bn": "Bengali (বাংলা)", "gu": "Gujarati (ગુજરાતી)", "pa": "Punjabi (ਪੰਜਾਬੀ)",
    "es": "Spanish", "fr": "French", "de": "German", "pt": "Portuguese", "ja": "Japanese",
}


def build_system_prompt(domain: str, personal_context: str = "", mobile_note: str = "", lang: str = "") -> str:
    base = DOMAIN_PROMPTS.get(domain, GENERAL_PROMPT)
    seg = f" {personal_context}" if personal_context else ""
    if mobile_note:
        base = base + "\n" + mobile_note
    _l = str(lang or "").strip().lower()
    if _l and not _l.startswith("en"):
        _name = _LANG_NAMES.get(_lang_base(_l), _l)
        base = base + (
            f"\nLANGUAGE: Reply ONLY in {_name} using natural, everyday spoken {_name.split(' (')[0]} — "
            "the same local accent and slang a native speaker uses. Never switch to English "
            "(keep common English technical words only when there is no natural local word). "
            "Write short sentences separated by commas and full stops so the voice sounds like a person talking, not a paragraph being read."
        )
    return base + seg


def router_order(prompt: str, has_image: bool, manual_model: str) -> list[str]:
    p = (prompt or "").lower()
    if has_image:
        order = ["nvidia/nemotron-3.5-super-vl:free", "google/gemma-4-31b-it", "meta/muse-ember", "xingchen-agi/xing4.0-29b-a4b:free", "recursive/flint-v1.0:free"]
    elif any(k in p for k in ("code", "python", "debug", "math", "reason", "explain", "how", "why", "what if")):
        order = ["xingchen-agi/xing4.0-29b-a4b:free", "google/gemma-4-31b-it", "nvidia/nemotron-3.5-super-vl:free", "meta/muse-ember", "recursive/flint-v1.0:free"]
    elif any(k in p for k in ("video", "news", "song", "music", "play", "movie", "film")):
        order = ["recursive/flint-v1.0:free", "meta/muse-ember", "xingchen-agi/xing4.0-29b-a4b:free", "nvidia/nemotron-3.5-super-vl:free", "google/gemma-4-31b-it"]
    else:
        order = ["nvidia/nemotron-3.5-super-vl:free", "recursive/flint-v1.0:free", "meta/muse-ember", "xingchen-agi/xing4.0-29b-a4b:free", "google/gemma-4-31b-it"]
    if manual_model and manual_model in order:
        order.remove(manual_model)
        order.insert(0, manual_model)
    return order


def call_or(api_key, model, messages, temp, toks, fast_chat=False, _has_image=False):
    import re as _re
    _prompt = ""
    try:
        for _m in reversed(messages):
            if _m.get("role") == "user":
                _c = _m.get("content")
                if isinstance(_c, str):
                    _prompt = _c
                elif isinstance(_c, list):
                    _prompt = " ".join([x.get("text", "") for x in _c if isinstance(x, dict) and x.get("type") == "text"])
                break
    except Exception:
        pass
    has_image = _has_image or any(isinstance(_m.get("content"), list) for _m in messages)
    # Fast chat: race the two fastest free models in parallel and take the first usable reply.
    # Goal: reply within ~2 seconds. Losing request finishes in the background (cancelled).
    if fast_chat and not has_image:
        import concurrent.futures as _cf
        headers={"Authorization":f"Bearer {api_key}","Content-Type":"application/json","X-OpenRouter-Title":"JARVIS AI","HTTP-Referer":"https://openrouter.ai/"}
        fast_models = ["google/gemma-4-31b-it", "nvidia/nemotron-3.5-super-vl:free"]

        def _fast_once(mname):
            payload={"model":mname,"messages":messages,"temperature":0.6,"max_tokens":512,"stream":False}
            resp=requests.post(API_URL,headers=headers,json=payload,timeout=7)
            if not resp.ok:
                return ""
            ch=resp.json().get("choices") or []
            if not ch:
                return ""
            c=(ch[0].get("message",{}) or {}).get("content") or ""
            return c.strip() if c else ""

        ex = _cf.ThreadPoolExecutor(max_workers=len(fast_models))
        futs = {ex.submit(_fast_once, m): m for m in fast_models}
        try:
            for fut in _cf.as_completed(futs):
                try:
                    c = fut.result()
                except Exception:
                    c = ""
                if c:
                    ex.shutdown(wait=False, cancel_futures=True)
                    return c, None
        finally:
            ex.shutdown(wait=False, cancel_futures=True)
        # Last resort: fall through to the full router (Nemotron → Flint → Muse Ember → Xing → Gemma) instead of giving up
        print("[JARVIS] fast path failed — falling back to full router")
    # Full router for vision / media
    fallbacks = router_order(_prompt, has_image, model)
    tried = []
    last_err = "Unknown error"
    for m in fallbacks:
        tried.append(m)
        headers={"Authorization":f"Bearer {api_key}","Content-Type":"application/json","X-OpenRouter-Title":"JARVIS AI","HTTP-Referer":"https://openrouter.ai/"}
        payload={"model":m,"messages":messages,"temperature":temp,"max_tokens":max(toks, 1024),"stream":False}
        _to = 20 if has_image else 8
        try: resp=requests.post(API_URL,headers=headers,json=payload,timeout=_to)
        except requests.Timeout: last_err="Timeout — try Fast mode."; continue
        except requests.RequestException as e: last_err=f"Network error: {e}"; continue
        if not resp.ok:
            try: d=resp.json(); e=d.get("error") or {}; detail=e.get("message") if isinstance(e,dict) else str(e)
            except Exception: detail=resp.text
            last_err=f"OpenRouter API error ({resp.status_code}) on {m}: {detail}"; continue
        data=resp.json(); ch=data.get("choices") or []
        if not ch: last_err=f"No choices from {m}: {data}"; continue
        msg = ch[0].get("message",{}) or {}
        content = (msg.get("content") or "").strip()
        if content and content != "None":
            return content, None
        reasoning = (msg.get("reasoning") or "").strip()
        if reasoning:
            # Extract final answer: last paragraph after reasoning block, or first complete sentence
            parts = [p.strip() for p in reasoning.split("\n\n") if p.strip()]
            if parts:
                # Heuristic: last part often contains answer
                candidate = parts[-1]
                if len(candidate) >= 20:
                    return candidate, None
            # Fallback: truncate reasoning to readable snippet
            clean = _re.sub(r"\s+", " ", reasoning).strip()
            if len(clean) >= 20:
                return clean[:800] + ("..." if len(clean)>800 else ""), None
        last_err = f"Empty content from {m}"
    return None, f"All models failed ({', '.join(tried)}). Last error: {last_err}"

def _script_clean(s: str) -> str:
    """Keep letters/marks/numbers of ANY script (Indic matras are marks!) + basic punctuation."""
    import unicodedata as _ud
    out = []
    for ch in s:
        if ch.isspace() or ch in ".,?!।'":
            out.append(ch)
            continue
        cat = _ud.category(ch)
        if cat[0] in ("L", "M", "N") or cat == "Cf":
            out.append(ch)
        else:
            out.append(" ")
    return "".join(out)


def humanize_for_speech(text: str, limit: int = 8000, allow_non_ascii: bool = None, lang: str = "") -> str:
    """Language-aware natural speech text: strips links/domains/citations/markdown, keeps the native
    script, and adds human pauses + native breathing fillers (hmm/umm) in the user's language."""
    import re as _re
    base = _lang_base(lang) if lang else "en"
    if allow_non_ascii is None:
        allow_non_ascii = base not in ("", "en")
    t = (text or "").strip()
    if not t:
        return ""
    # strip code, tags, media markers
    t = _re.sub(r"```.*?```", " ", t, flags=_re.DOTALL)
    t = _re.sub(r"`[^`]*`", " ", t)
    t = _re.sub(r"<[^>]+>", " ", t)
    t = _re.sub(r"\[(VIDEO|MUSIC)\s*:[^\]]*\]", " ", t, flags=_re.IGNORECASE)
    # links -> label; citations "(Title — URL)" -> title; bare domains/emails gone (never read "dot")
    t = _re.sub(r"(?im)^\s*(?:sources?|references?|links?|citations?)\s*:.*$", " ", t)
    t = _re.sub(r"\[([^\]]+)\]\((https?://[^)]+)\)", r"\1", t)
    t = _re.sub(r"\(\s*(?:source|sources|link|url|citation|via)\b[^()]*\)", " ", t, flags=_re.IGNORECASE)
    t = _re.sub(r"\(\s*([^()]*?)\s*[—–-]\s*(?:https?://|www\.)[^()]*?\)", r" \1 ", t)
    _w_site = (_LANG_SPEECH_WORDS.get(base) or _LANG_SPEECH_WORDS["en"]).get("website", "the website")
    t = _re.sub(r"https?://[^\s)\]>]+", " %s " % _w_site, t)
    t = _re.sub(r"\bwww\.\S+", " %s " % _w_site, t, flags=_re.IGNORECASE)
    t = _re.sub(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b", " ", t)
    t = _re.sub(r"\b(?:[\w-]+\.)+(?:com|org|net|io|ai|dev|in|co|me|app|gov|edu|info|xyz|site)(?:/\S*)?\b", " %s " % _w_site, t, flags=_re.IGNORECASE)
    t = _re.sub(r"\bdot\s+(?:com|org|net|in|io|ai|dev)\b", " %s " % _w_site, t, flags=_re.IGNORECASE)
    # markdown tables, headings, emphasis, "Sources:"
    t = _re.sub(r"(?m)^\s*\|?[\s:|-]{5,}\|?\s*$", " ", t)
    t = _re.sub(r"\|", " , ", t)
    t = _re.sub(r"#{1,6}\s*", " ", t)
    t = _re.sub(r"\*\*(.*?)\*\*", r"\1", t)
    t = _re.sub(r"\*(.*?)\*", r"\1", t)
    t = _re.sub(r"(?i)\bsources?\s*:", " ", t)
    # language-aware symbols (never English words inside an Indian-language sentence)
    _w = _LANG_SPEECH_WORDS.get(base) or _LANG_SPEECH_WORDS["en"]
    t = _re.sub(r"°\s*[cC]\b", " %s " % _w["degrees"], t)
    t = _re.sub(r"°\s*[fF]\b", " %s " % _w["degrees"], t)
    t = t.replace("%", " %s " % _w["percent"])
    t = t.replace("°", " %s " % _w["degrees"])
    t = _re.sub(r"\s&\s", " %s " % _w["and"], t)
    # sentence split (supports Devanagari danda + newlines)
    t = t.replace("\r", "\n")
    parts = _re.split(r"(?<=[.!?।])\s+|\n+", t)
    cleaned = []
    for s in parts:
        s = (s or "").strip()
        if not s:
            continue
        s = _re.sub(r"^\s*(?:[-•*○◦▪·~]+\s*|\d+\s*[.)]\s*)", "", s)
        if allow_non_ascii:
            # Unicode categories keep Indic vowel signs (matras) intact — never mangle words.
            s = _script_clean(s)
        else:
            s = _re.sub(r"<[^>]+>", " ", s)
            s = _re.sub(r"[^\x00-\x7F]", " ", s)
            s = _re.sub(r"[^A-Za-z0-9\s,\.\?\!']", " ", s)
        # punctuation tidy: no space before marks, no doubled or dangling marks
        s = _re.sub(r"\s+", " ", s)
        s = _re.sub(r"\s+([,.;:!?।])", r"\1", s)
        s = _re.sub(r"([,.;:!?])\1+", r"\1", s)
        s = _re.sub(r",\s*,+", ",", s)
        s = _re.sub(r"([.!?])\s*,+", r"\1", s)
        s = _re.sub(r",\s*([.!?])", r"\1", s)
        s = _re.sub(r"\s+(?:at|on|in|from|via)\s*([.!?])$", r"\1", s, flags=_re.IGNORECASE)
        s = s.strip(" ,-;:")
        _bare = s.strip(" .,?!।").strip().lower()
        if _bare in ("the website", "website", "the link", "link") or _bare == str(_w_site).strip().lower():
            continue
        if s:
            if s.endswith(("?", "!")):
                pass
            elif s.endswith("."):
                pass
            else:
                s = s.rstrip("।.?!,;:") + "."
            cleaned.append(s)
    if not cleaned:
        return ""
    # human breathing: one native filler (hmm / umm / achha…) after the opening sentence
    _fill = _LANG_FILLERS.get(base) or _LANG_FILLERS["en"]
    import zlib as _zl
    if len(cleaned) >= 2 and len(cleaned[0]) >= 10:
        cleaned.insert(1, _fill[_zl.crc32(t.encode("utf-8")) % len(_fill)])
    out = " ".join(cleaned)
    # longer answers get a thinking-style gap between the first two sentences
    if len(cleaned) >= 4:
        out = out.replace(". ", ". … ", 2)
    out = _re.sub(r"\s+", " ", out)
    if len(out) > limit:
        out = out[:limit].rsplit(". ", 1)[0].rstrip(".?!।") + "."
    return out


def _ssml_human(text: str) -> str:
    """Plain text only — SSML tags were being read aloud as hertz/semicolon/comma. Never add SSML."""
    return text


_LANG_VOICES = {
    "en-us": {"male": "en-US-BrianNeural", "female": "en-US-EmmaNeural"},
    "en-in": {"male": "en-IN-PrabhatNeural", "female": "en-IN-NeerjaNeural"},
    "en-gb": {"male": "en-GB-RyanNeural", "female": "en-GB-SoniaNeural"},
    "en-au": {"male": "en-AU-WilliamMultilingualNeural", "female": "en-AU-NatashaNeural"},
    "hi-in": {"male": "hi-IN-MadhurNeural", "female": "hi-IN-SwaraNeural"},
    "te-in": {"male": "te-IN-MohanNeural", "female": "te-IN-ShrutiNeural"},
    "kn-in": {"male": "kn-IN-GaganNeural", "female": "kn-IN-SapnaNeural"},
    "ta-in": {"male": "ta-IN-ValluvarNeural", "female": "ta-IN-PallaviNeural"},
    "ml-in": {"male": "ml-IN-MidhunNeural", "female": "ml-IN-SobhanaNeural"},
    "mr-in": {"male": "mr-IN-ManoharNeural", "female": "mr-IN-AarohiNeural"},
    "bn-in": {"male": "bn-IN-BashkarNeural", "female": "bn-IN-TanishaaNeural"},
    "gu-in": {"male": "gu-IN-NiranjanNeural", "female": "gu-IN-DhwaniNeural"},
    "es-es": {"male": "es-ES-AlvaroNeural", "female": "es-ES-ElviraNeural"},
    "fr-fr": {"male": "fr-FR-HenriNeural", "female": "fr-FR-DeniseNeural"},
    "de-de": {"male": "de-DE-ConradNeural", "female": "de-DE-KatjaNeural"},
    "pt-br": {"male": "pt-BR-AntonioNeural", "female": "pt-BR-FranciscaNeural"},
    "ja-jp": {"male": "ja-JP-KeitaNeural", "female": "ja-JP-NanamiNeural"},
}
# Backwards-compatible alias (keys are lowercase locales).
_VOICE_GENDER_MAP = _LANG_VOICES

_LANG_FILLERS = {
    "hi": ["हम्म,", "उम्म,", "अच्छा,"],
    "te": ["హమ్మ్,", "అం,", "అలాగా,"],
    "kn": ["ಹ್ಮ್,", "ಅಂದ್ರೆ,", "ಸರಿ,"],
    "ta": ["ம்,", "அப்படியா,"],
    "ml": ["ഹ്മ്മ്,", "അല്ലേ,"],
    "mr": ["हम्म,", "बरं,"],
    "bn": ["হুম,", "আচ্ছা,"],
    "gu": ["હમ્મ,", "ઠીક,"],
    "en": ["hmm,", "uh,", "well,"],
}

_LANG_SPEECH_WORDS = {
    "hi": {"percent": "प्रतिशत", "and": "और", "degrees": "डिग्री", "website": "वेबसाइट"},
    "te": {"percent": "శాతం", "and": "మరియు", "degrees": "డిగ్రీలు", "website": "వెబ్‌సైట్"},
    "kn": {"percent": "ಪ್ರತಿಶತ", "and": "ಮತ್ತು", "degrees": "ಡಿಗ್ರಿ", "website": "ವೆಬ್‌ಸೈಟ್"},
    "ta": {"percent": "சதவீதம்", "and": "மற்றும்", "degrees": "டிகிரி", "website": "இணையதளம்"},
    "ml": {"percent": "ശതമാനം", "and": "കൂടാതെ", "degrees": "ഡിഗ്രി", "website": "വെബ്സൈറ്റ്"},
    "mr": {"percent": "टक्के", "and": "आणि", "degrees": "अंश", "website": "वेबसाइट"},
    "bn": {"percent": "শতাংশ", "and": "এবং", "degrees": "ডিগ্রি", "website": "ওয়েবসাইট"},
    "gu": {"percent": "ટકા", "and": "અને", "degrees": "ડિગ્રી", "website": "વેબસાઇટ"},
    "en": {"percent": "percent", "and": "and", "degrees": "degrees", "website": "the website"},
}


def _lang_base(lang: str) -> str:
    return (lang or "en-US").strip().lower().replace("_", "-").split("-")[0]


_SCRIPT_RANGES = {
    "te-IN": (0x0C00, 0x0C7F),
    "hi-IN": (0x0900, 0x097F),
    "kn-IN": (0x0C80, 0x0CFF),
    "ta-IN": (0x0B80, 0x0BFF),
    "ml-IN": (0x0D00, 0x0D7F),
    "bn-IN": (0x0980, 0x09FF),
    "gu-IN": (0x0A80, 0x0AFF),
}


def detect_text_lang(text: str) -> str:
    """Detect the dominant Indic script in a reply (so the voice always matches the text)."""
    t = text or ""
    best, best_n = "", 0
    for loc, (lo, hi) in _SCRIPT_RANGES.items():
        n = sum(1 for ch in t if lo <= ord(ch) <= hi)
        if n > best_n:
            best, best_n = loc, n
    return best if best_n >= 10 else ""


def speech_lang_for(text: str, selected: str = "en-US") -> str:
    """Language to speak in: the reply's own script wins; otherwise keep the selected language
    (English replies under an Indian language get the Indian-English accent, not American)."""
    sel = str(selected or "en-US").strip()
    det = detect_text_lang(text)
    if det:
        return det
    if _lang_base(sel) not in ("en", ""):
        return "en-IN"
    return sel or "en-US"


def voice_for_lang(lang: str = "en-US", gender: str = "auto", selected: str = "") -> str:
    """Pick the native neural voice for the user's speech language (accent-correct)."""
    raw = (lang or "en-US").strip().lower().replace("_", "-")
    base = _lang_base(raw)
    if isinstance(selected, (tuple, list)):
        selected = selected[1] if len(selected) > 1 else ""
    selected = str(selected or "").strip()
    g = str(gender or "auto").strip().lower()
    if g not in ("male", "female"):
        g = "female" if base in ("te", "hi", "kn", "ta", "ml", "mr", "bn", "gu") else "male"
    table = _LANG_VOICES.get(raw)
    if not table:
        for _k, _vals in _LANG_VOICES.items():
            if _k.split("-")[0] == base:
                table = _vals
                break
    if base == "en" and selected and _lang_base(selected) == "en":
        return _apply_voice_gender(selected, gender)
    if table:
        return table[g]
    if selected:
        return _apply_voice_gender(selected, gender)
    return "en-US-GuyNeural"


def _apply_voice_gender(voice: str, gender: str = "auto") -> str:
    g = str(gender or "auto").strip().lower()
    if g not in ("male", "female"):
        return voice
    try:
        lang = (voice.split("-")[0] + "-" + voice.split("-")[1]).lower()
    except Exception:
        return voice
    return _VOICE_GENDER_MAP.get(lang, {}).get(g) or voice


def _fallback_voice(voice: str, lang: str = "") -> str:
    """Known-good voice for the language, used when a selected voice returns no audio.
    Prefers the opposite-gender native voice so a failed voice still gets a retry."""
    raw = (lang or voice or "").strip().lower().replace("_", "-")
    table = _LANG_VOICES.get(raw) or {}
    if not table:
        for _k, _vals in _LANG_VOICES.items():
            if _k.split("-")[0] == _lang_base(raw):
                table = _vals
                break
    cand = ""
    if table:
        if voice == table.get("female"):
            cand = table.get("male") or ""
        else:
            cand = table.get("female") or table.get("male") or ""
    if not cand:
        cand = "en-US-GuyNeural"
    return cand


def synthesize_human_speech(text: str, voice: str = "en-US-GuyNeural", gender: str = "auto", lang: str = "") -> bytes:
    """Natural neural speech: native-language voice, human pacing (-10% Indic / -6% English),
    gentle thinking pauses, and native breathing fillers — never robotic or English-accented."""
    import edge_tts
    voice = _apply_voice_gender(voice, gender)
    base = (lang or voice.split("-")[0]).strip().lower().split("-")[0]
    human = humanize_for_speech(text, limit=700, lang=(lang or voice))
    if not human:
        return b""
    rate = "-10%" if base in ("hi", "te", "kn", "ta", "ml", "mr", "bn", "gu") else "-6%"
    _err = {"type": ""}

    def _once(v: str, timeout: float = 12) -> bytes:
        async def _gen() -> bytes:
            comm = edge_tts.Communicate(text=human, voice=v, rate=rate)
            with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
                path = tmp.name
            try:
                await asyncio.wait_for(comm.save(path), timeout)
                return Path(path).read_bytes()
            finally:
                try: os.unlink(path)
                except OSError: pass
        try:
            return asyncio.run(_gen())
        except Exception as e:
            _err["type"] = type(e).__name__
            return b""

    data = _once(voice, 9)
    if not data:
        # A voice can intermittently return no audio or time out — retry once with another native voice.
        fb = _fallback_voice(voice, lang or voice)
        if fb and fb != voice:
            data = _once(fb, 8)
    return data


def voice_html(text: str, audio_b64: str | None, lang: str = "", speak_token: str = "", auto: bool = False) -> str:
    """Speak a just-generated reply ONCE. Restored history stays silent.
    Uses one shared player on the parent window; never replays on reruns, voiceschanged or clicks."""
    import json as _json
    safe = _json.dumps(text)
    langjson = _json.dumps(lang or "en-US")
    b64json = _json.dumps(audio_b64 or "")
    tokenjson = _json.dumps(speak_token or "")
    autojs = "true" if auto else "false"
    return f"""
<style>body{{margin:0;background:transparent;}}</style>
<script>
(function(){{
  var full = {safe};
  var ulang = {langjson};
  var audioB64 = {b64json};
  var stoken = {tokenjson};
  var auto = {autojs};
  if (!auto || !stoken) return;
  // Single shared player on the parent window (survives iframe remounts)
  var W = (function(){{ try {{ if (window.parent && window.parent.document) return window.parent }} catch (e) {{}} return window }})()
  var G = W.__jarvisTTS || (W.__jarvisTTS = {{ audio: null, token: '', playing: false, bc: null, timer: null, srcToken: '', startedAt: 0 }})
  var KEY = 'jv_spoken_' + stoken
  function alreadySpoken() {{
    try {{ if (W.sessionStorage && W.sessionStorage.getItem(KEY) === '1') return true }} catch (e) {{}}
    try {{
      var ts = parseInt((W.localStorage && W.localStorage.getItem(KEY)) || '0', 10)
      if (ts && (Date.now() - ts) < 43200000) return true
    }} catch (e) {{}}
    return false
  }}
  function markSpoken() {{
    try {{ if (W.sessionStorage) W.sessionStorage.setItem(KEY, '1') }} catch (e) {{}}
    try {{ if (W.localStorage) W.localStorage.setItem(KEY, String(Date.now())) }} catch (e) {{}}
  }}
  function unmarkSpoken() {{
    try {{ if (W.sessionStorage) W.sessionStorage.removeItem(KEY) }} catch (e) {{}}
    try {{ if (W.localStorage) W.localStorage.removeItem(KEY) }} catch (e) {{}}
  }}
  if (alreadySpoken()) return;
  function noteSpeaking(on) {{
    try {{ W.__jarvisSpeaking = !!on }} catch (e) {{}}
    if (!on) {{ try {{ W.__jarvisSpeechEnd = Date.now() }} catch (e) {{}} }}
    try {{ if (G.bc) G.bc.postMessage(on ? 'SPEAKING_START' : 'SPEAKING_END') }} catch (e) {{}}
  }}
  function stopAll() {{
    if (G.audio) {{ try {{ G.audio.pause() }} catch (e) {{}} try {{ G.audio.currentTime = 0 }} catch (e) {{}} }}
    if ('speechSynthesis' in window) {{ try {{ window.speechSynthesis.cancel() }} catch (e) {{}} }}
    try {{ if (W !== window && W.speechSynthesis) W.speechSynthesis.cancel() }} catch (e) {{}}
    G.playing = false; G.token = ''
    noteSpeaking(false)
  }}
  try {{
    if (!G.bc) {{ G.bc = new W.BroadcastChannel('jarvis_tts'); G.bc.onmessage = function(e){{ if(e.data==='STOP') stopAll() }} }}
  }} catch (e) {{}}
  function browserSpeak(){{
    if(!('speechSynthesis' in window) || !full) return;
    try {{
      stopAll()
      var msg = new SpeechSynthesisUtterance(full);
      msg.rate = 0.95; msg.pitch = 0.95; msg.volume = 1.0;
      var voices = speechSynthesis.getVoices();
      var ul = String(ulang || 'en-US').toLowerCase().replace('_', '-');
      var ub = ul.split('-')[0];
      var langVoice = voices.find(function(v) {{ return String(v.lang || '').toLowerCase().replace('_', '-').split('-')[0] === ub; }});
      var preferred = langVoice
        || voices.find(v => /Guy|David|Daniel|Alex|Microsoft Guy/i.test(v.name + ' ' + v.voiceURI))
        || voices.find(v => /^en[-_]US/i.test(v.lang) && /male|guy|david/i.test(v.name))
        || voices.find(v => v.lang.startsWith('en-US'))
        || voices.find(v => v.lang.startsWith('en'));
      if(preferred) {{ msg.voice = preferred; try {{ msg.lang = (ulang || preferred.lang || '') }} catch (e) {{}} }}
      msg.onstart = function () {{ noteSpeaking(true) }}
      msg.onend = function () {{ noteSpeaking(false); G.playing = false; G.token = '' }}
      msg.onerror = function () {{ noteSpeaking(false); G.playing = false; G.token = '' }}
      speechSynthesis.speak(msg);
      G.playing = true
      G.token = stoken
    }} catch(e) {{}}
  }}
  function tryPlay(){{
    markSpoken();
    if(!audioB64) {{ browserSpeak(); return; }}
    var a = G.audio;
    try {{ if (!a && W !== window && W.Audio) {{ a = new W.Audio(); a.setAttribute('playsinline', '') }} }} catch (e) {{}}
    if (!a) {{ try {{ a = new Audio() }} catch (e) {{}} }}
    if (!a) {{ unmarkSpoken(); browserSpeak(); return; }}
    try {{
      if (G.srcToken !== stoken || !a.src) {{
        a.src = 'data:audio/mp3;base64,' + audioB64
        G.srcToken = stoken
        try {{ a.load() }} catch (e) {{}}
      }} else {{
        try {{ a.currentTime = 0 }} catch (e) {{}}
      }}
      G.audio = a
      G.playing = true
      G.token = stoken
      G.startedAt = Date.now()
      a.onended = function () {{ stopAll() }}
      a.onerror = function () {{ unmarkSpoken(); stopAll(); browserSpeak() }}
      noteSpeaking(true)
      var p;
      try {{ p = a.play(); }} catch (e) {{ unmarkSpoken(); browserSpeak(); return; }}
      if(p && p.catch) p.catch(function(){{ unmarkSpoken(); stopAll(); browserSpeak(); }});
    }} catch (e) {{ unmarkSpoken(); browserSpeak(); }}
  }}
  tryPlay();
  // STOP from parent-doc messages (mic, send, tiles, etc.)
  try {{
    window.addEventListener('message', function(e) {{ if (e.data && e.data.type === 'JARVIS_STOP_TTS') stopAll() }})
  }} catch (e) {{}}
}})();
</script>
"""

def reactor_html():
    return """
<style>body{margin:0;background:transparent;} .rw{display:flex;flex-direction:column;align-items:center;padding:6px 0;} #rc{width:360px;height:260px;display:block;} .rt{font-family:Orbitron,monospace;color:#00d4ff;font-size:34px;letter-spacing:8px;font-weight:900;text-shadow:0 0 24px rgba(0,212,255,0.9);margin-top:-18px;} .rs{color:#ff4da6;font-family:Orbitron,monospace;letter-spacing:5px;font-size:12px;margin-top:2px;text-shadow:0 0 12px rgba(255,77,166,0.6);} video{width:100%;height:260px;object-fit:cover;border-radius:8px;box-shadow:0 0 24px rgba(0,212,255,0.25);}</style>
<div class="rw"><video autoplay muted loop playsinline src="/static/gui_bg.mp4" style="width:100%;height:220px;object-fit:cover;border-radius:8px;"></video><div class="rt">JARVIS</div><div class="rs">AI ASSISTANT</div></div>
<script>
(function(){const c=document.getElementById('rc');if(!c)return;const x=c.getContext('2d');var d=window.devicePixelRatio||1;function rs(){c.width=c.clientWidth*d;c.height=300*d;}window.addEventListener('resize',rs);rs();let t=0;
function ring(cx,cy,r,rot,dash,col,lw){x.beginPath();for(let a=0;a<Math.PI*2;a+=0.02){if(dash&&Math.sin(a*7+rot)<-0.25)continue;let px=cx+Math.cos(a+rot)*r,py=cy+Math.sin(a+rot)*r*0.62;a===0?x.moveTo(px,py):x.lineTo(px,py);}x.strokeStyle=col;x.lineWidth=lw*d;x.shadowColor=col;x.shadowBlur=10*d;x.stroke();}
function dot(cx,cy,r,a,col){let px=cx+Math.cos(a)*r,py=cy+Math.sin(a)*r*0.62;x.beginPath();x.arc(px,py,5*d,0,7);x.fillStyle=col;x.shadowColor=col;x.shadowBlur=16*d;x.fill();}
function helmet(cx,cy,s){x.save();x.translate(cx,cy-30*d);x.scale(s,s);x.strokeStyle='#00d4ff';x.shadowColor='#00d4ff';x.shadowBlur=16*d;x.lineWidth=2.2;x.beginPath();
x.moveTo(-42,-28);x.lineTo(-32,-42);x.quadraticCurveTo(0,-52,32,-42);x.lineTo(42,-28);x.quadraticCurveTo(40,-6,30,10);x.lineTo(26,26);x.lineTo(12,36);x.lineTo(-12,36);x.lineTo(-26,26);x.lineTo(-30,10);x.quadraticCurveTo(-40,-6,-42,-28);x.stroke();
x.beginPath();x.moveTo(-30,-14);x.lineTo(-8,-8);x.lineTo(8,-8);x.lineTo(30,-14);x.stroke();
x.beginPath();x.moveTo(-18,2);x.lineTo(-6,8);x.lineTo(6,8);x.lineTo(18,2);x.stroke();
x.beginPath();x.moveTo(-10,28);x.lineTo(10,28);x.stroke();x.restore();}
function draw(){var w=c.width,h=c.height,cx=w/2,cy=h/2-20*d,R=Math.min(w,h)*0.36;x.clearRect(0,0,w,h);x.fillStyle='#05070d';x.fillRect(0,0,w,h);
ring(cx,cy,R*1.22,t*0.4,true,'rgba(0,212,255,0.7)',1.5);ring(cx,cy,R*0.98,-t*0.7,false,'rgba(255,77,166,0.85)',2.5);ring(cx,cy,R*0.78,t*1.1,true,'rgba(0,212,255,0.5)',1.5);ring(cx,cy,R*0.6,-t*1.4,false,'rgba(0,255,179,0.4)',1);
dot(cx,cy,R*1.22,t*0.9,'#00d4ff');dot(cx,cy,R*0.98,-t*1.2,'#ff4da6');dot(cx,cy,R*0.78,t*1.6,'#00ffb3');
helmet(cx,cy,1.15);
for(let i=0;i<3;i++){let rr=R*0.4+((t*20+i*16)%30)*d;x.beginPath();x.ellipse(cx,cy+R*0.72,rr,rr*0.26,0,0,7);x.strokeStyle='rgba(0,212,255,'+(0.28-i*0.07)+')';x.lineWidth=1*d;x.stroke();}
t+=0.016;requestAnimationFrame(draw);}draw();})();
</script>"""

def mic_status_html(state: str) -> str:
    s = state or "sleeping"
    listening = s == "listening"
    thinking = s == "thinking"
    col = "#00d4ff" if listening else ("#ffb020" if thinking else "#3a5a75")
    glow = f"0 0 26px {col}, inset 0 0 14px rgba(2,8,16,0.6)" if (listening or thinking) else "0 0 14px rgba(2,8,16,0.6)"
    op = "0.95" if (listening or thinking) else "0.6"
    anim = "micpulse 1.6s ease-out infinite" if (listening or thinking) else "none"
    cls = "listening" if listening else ("thinking" if thinking else "sleeping")
    micfill = "#9fe8ff" if listening else ("#ffd28a" if thinking else "#5b7a94")
    return f"""<style>
.micstatus{{display:flex;flex-direction:column;align-items:center;padding:14px 0 2px;}}
.micstatus .disc{{position:relative;width:58px;height:58px;border-radius:50%;background:radial-gradient(circle at 34% 30%, rgba(26,72,112,0.92), rgba(5,16,32,0.97) 74%);border:2px solid {col};box-shadow:{glow};display:flex;align-items:center;justify-content:center;opacity:{op};}}
.micstatus .disc .ring{{position:absolute;top:0;left:0;width:58px;height:58px;border-radius:50%;border:2px solid {col};opacity:0;animation:{anim} ease-out;pointer-events:none;}}
.micstatus.sleeping .disc{{border-color:#3a5a75;box-shadow:0 0 14px rgba(2,8,16,0.6);opacity:0.6;}}
.micstatus.sleeping .disc .ring{{display:none;}}
.micstatus.listening .disc .ring{{animation-name:micpulse;animation-timing-function:ease-out;animation-iteration-count:infinite;animation-duration:1.6s;}}
.micstatus.thinking .disc .ring{{animation-name:micpulse;animation-timing-function:ease-out;animation-iteration-count:infinite;animation-duration:1.6s;}}
@keyframes micpulse{{0%{{transform:scale(0.85);opacity:0.85}}100%{{transform:scale(1.4);opacity:0}}}}
</style>
<div class="micstatus {cls}"><div class="disc"><svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="{micfill}" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="2.2" width="6" height="11.2" rx="3" fill="{micfill}" stroke="none"/><path d="M5.4 10.8v1.4a6.6 6.6 0 0 0 13.2 0v-1.4"/><path d="M12 18.6v3.1"/><path d="M8.4 21.7h7.2"/></svg><div class="ring"></div></div></div>
"""


def editor_html(layout: dict) -> str:
    import json as _j
    panels = [
        ("clock", "CLOCK", 20, 20, 240, 78),
        ("system", "SYSTEM STATUS", 20, 110, 240, 90),
        ("music", "MUSIC TERMINAL", 20, 210, 240, 110),
        ("weather", "WEATHER", 20, 330, 240, 90),
        ("jarvis", "JARVIS", 285, 20, 420, 320),
        ("chat", "CHAT", 285, 350, 420, 220),
        ("camera", "CAMERA VISION — LIVE", 730, 20, 440, 180),
        ("video", "VIDEO — NEWS / YOUTUBE", 730, 210, 320, 180),
        ("tasks", "TASKS — TO-DO LIST", 730, 400, 320, 180),
    ]
    # Override with saved positions if present
    saved = layout.get("panels", {})
    def pos(key, x, y, w, h):
        s = saved.get(key, {})
        return (s.get("x", x), s.get("y", y), s.get("w", w), s.get("h", h))
    preview = {
        "clock": "🕐 Live clock — 02:44 PM",
        "system": "CPU 54% · RAM 68% · GPU 12%",
        "music": "♪ Blinding Lights — The Weeknd<br><small>Click play inside player for sound</small>",
        "weather": "🌡 24.6°C Bengaluru",
        "jarvis": "◉ JARVIS AI CORE<br>Helm reactor — always moving",
        "chat": "💬 Your conversation appears here…",
        "camera": "📷 Camera preview area — Live",
        "video": "▶ Video player area — YouTube",
        "tasks": "☑ Complete DSA — 2:00 PM<br>☐ Work on AI project — 5:00 PM",
    }
    divs = ""
    for key, title, x, y, w, h in panels:
        px, py, pw, ph = pos(key, x, y, w, h)
        body = preview.get(key, key.upper())
        divs += f'<div class="panel" data-key="{key}" style="left:{px}px;top:{py}px;width:{pw}px;height:{ph}px;"><div class="p-head">{title}<span class="grip">⠿</span></div><div class="p-body">{body}</div><div class="resize"></div></div>'
    init_json = _j.dumps({p[0]: {"x": pos(p[0], p[2], p[3], p[4], p[5])[0], "y": pos(p[0], p[2], p[3], p[4], p[5])[1], "w": pos(p[0], p[2], p[3], p[4], p[5])[2], "h": pos(p[0], p[2], p[3], p[4], p[5])[3]} for p in panels})
    return f"""
<style>
body{{margin:0;background:#0a1628;font-family:Rajdhani,sans-serif;color:#e8f1ff;}}
#board{{position:relative;width:1100px;height:600px;margin:0 auto;background:linear-gradient(rgba(0,212,255,0.07) 1px, transparent 1px),linear-gradient(90deg, rgba(0,212,255,0.07) 1px, transparent 1px);background-size:32px 32px;border:1px dashed rgba(0,212,255,0.4);}}
.panel{{position:absolute;background:#0d1a2e;border:1px solid #00d4ff;border-radius:6px;box-sizing:border-box;cursor:grab;overflow:hidden;}}
.panel:active{{cursor:grabbing;z-index:10;}}
.p-head{{display:flex;justify-content:space-between;padding:6px 10px;font-family:Orbitron,monospace;font-size:10px;letter-spacing:2px;color:#00d4ff;border-bottom:1px solid rgba(0,212,255,0.3);}}
.p-body{{padding:10px;font-size:13px;color:#8aa4bd;text-align:center;}}
.resize{{position:absolute;right:0;bottom:0;width:20px;height:20px;cursor:nwse-resize;background:linear-gradient(135deg, transparent 50%, #00d4ff 50%);}}
#saveBar{{text-align:center;margin:10px;}}
button{{background:#00d4ff;color:#05070d;border:none;border-radius:999px;padding:10px 26px;font-weight:800;cursor:pointer;}}
</style>
<div id="board">{divs}</div>
<div id="saveBar"><button onclick="saveLayout()">💾 SAVE LAYOUT</button></div>
<script>
var pos = {init_json};
document.querySelectorAll('.panel').forEach(function(el){{
  var key = el.dataset.key;
  var startX, startY, startL, startT, startW, startH, mode=null;
  el.addEventListener('mousedown', function(e){{
    mode = e.target.classList.contains('resize') ? 'resize' : 'move';
    startX = e.clientX; startY = e.clientY;
    startL = el.offsetLeft; startT = el.offsetTop;
    startW = el.offsetWidth; startH = el.offsetHeight;
    e.preventDefault();
    function mv(ev){{
      if(mode==='move'){{ el.style.left = (startL + ev.clientX - startX) + 'px'; el.style.top = (startT + ev.clientY - startY) + 'px'; }}
      else {{ el.style.width = Math.max(120, startW + ev.clientX - startX) + 'px'; el.style.height = Math.max(60, startH + ev.clientY - startY) + 'px'; }}
    }}
    function up(){{
      window.removeEventListener('mousemove', mv); window.removeEventListener('mouseup', up);
      pos[key] = {{x: el.offsetLeft, y: el.offsetTop, w: el.offsetWidth, h: el.offsetHeight}};
    }}
    window.addEventListener('mousemove', mv); window.addEventListener('mouseup', up);
  }});
}});
function saveLayout(){{
  var data = JSON.stringify(pos);
  try {{ localStorage.setItem('jarvis_layout', data); }} catch(e){{}}
  var url = window.location.origin + window.location.pathname + '?layout=' + encodeURIComponent(data);
  try {{ window.parent.location.href = url; }} catch(e) {{}}
  try {{ window.top.location.href = url; }} catch(e) {{}}
  window.location.href = url;
}}
</script>
"""


def clock_html():
    return """<style>body{margin:0;background:transparent;} #ck{display:block;text-align:center;background:rgba(5,7,13,0.92);border:1px solid rgba(0,212,255,0.5);border-radius:10px;padding:10px 18px;color:#00d4ff;font-family:Orbitron,monospace;box-sizing:border-box;} #t{font-size:34px;font-weight:900;letter-spacing:3px;} #d{font-size:13px;letter-spacing:2px;color:#8aa4bd;}</style><div><div id="ck"><div id="t">--:-- --</div><div id="d">---</div></div></div><script>function k(){var n=new Date();document.getElementById('t').textContent=n.toLocaleTimeString('en-US',{hour:'2-digit',minute:'2-digit'});document.getElementById('d').textContent=n.toLocaleDateString('en-GB',{weekday:'short',day:'2-digit',month:'short',year:'numeric'});}k();setInterval(k,1000);</script>"""

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Orbitron:wght@500;700;900&family=Rajdhani:wght@400;500;600;700&display=swap');
.stApp{background-color:#020914 !important;background-image:linear-gradient(rgba(5,7,13,0.55), rgba(5,7,13,0.55)), url(__BG_URI__) !important;background-size:cover !important;background-position:center !important;background-attachment:fixed !important;color:#DDF7FF !important;font-family:'Rajdhani','Segoe UI',sans-serif !important;}
/* Cinematic Iron Man lab backdrop */
.stApp::before{background:radial-gradient(circle at 85% 15%, rgba(255,32,64,0.22) 0%, transparent 55%),radial-gradient(circle at 10% 85%, rgba(0,212,255,0.26) 0%, transparent 55%),radial-gradient(circle at 50% 45%, rgba(0,80,160,0.28) 0%, transparent 60%),repeating-linear-gradient(0deg, rgba(0,212,255,0.03) 0 1px, transparent 1px 44px),repeating-linear-gradient(90deg, rgba(0,212,255,0.03) 0 1px, transparent 1px 44px) !important;}
.hud{position:relative;}
.hud::before,.hud::after{content:'';position:absolute;width:14px;height:14px;border:2px solid rgba(0,212,255,0.6);pointer-events:none;}
.hud::before{top:-2px;left:-2px;border-right:none;border-bottom:none;border-radius:10px 0 0 0;}
.hud::after{bottom:-2px;right:-2px;border-left:none;border-top:none;border-radius:0 0 10px 0;}
.stApp::before{content:'';position:fixed;inset:0;background:radial-gradient(circle at 85% 15%, rgba(255,32,64,0.18) 0%, transparent 55%),radial-gradient(circle at 10% 85%, rgba(0,212,255,0.22) 0%, transparent 55%),repeating-linear-gradient(0deg, rgba(0,212,255,0.025) 0 1px, transparent 1px 44px),repeating-linear-gradient(90deg, rgba(0,212,255,0.025) 0 1px, transparent 1px 44px);pointer-events:none;z-index:0;}
.stApp::after{content:'';position:fixed;inset:0;background:linear-gradient(180deg, transparent 0%, rgba(255,32,64,0.06) 100%);pointer-events:none;z-index:0;}
#MainMenu, header[data-testid="stHeader"], footer{display:none !important;}
[data-testid="stSidebar"]{display:none !important;}
.stApp{max-width:1920px;max-height:1080px;margin:0 auto;padding:120px 2.5rem 30px 2.5rem !important;height:100vh;max-height:1080px;overflow:hidden;position:relative;z-index:1;}
.block-container{padding:0 !important;height:100vh;max-height:1080px;overflow:hidden;position:relative;z-index:1;padding-top:120px !important;padding-bottom:30px !important;}
.block-container{padding:0 !important;height:100vh;overflow:hidden;position:relative;z-index:1;padding-top:100px !important;padding-bottom:40px !important;}
[data-testid="stCameraInput"] { width: 460px !important; max-width: 460px !important; height: 258px !important; max-height: 258px !important; overflow: hidden !important; margin: 0 auto !important; }
[data-testid="stCameraInput"] video, [data-testid="stCameraInput"] img, [data-testid="stCameraInput"] canvas { width: 460px !important; height: 258px !important; max-width: 460px !important; max-height: 258px !important; object-fit: cover !important; object-position: center 20% !important; display: block !important; }
.hud{border:1.5px solid #08CFFF !important;border-radius:16px;padding:15px;margin-bottom:21px;background:rgba(6,24,39,0.92) !important;box-shadow:0 0 20px rgba(8,207,255,0.14);position:relative;}
.ht{color:#00d4ff;font-size:11px;letter-spacing:3px;text-shadow:0 0 12px rgba(0,212,255,0.7);display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;}
.ht::after{content:'▣  ✕';font-size:10px;color:#00d4ff;letter-spacing:1px;}
.tabbtn-red{background:#ff2040 !important;color:#fff !important;border:1px solid #ff2040 !important;font-weight:700;}
.chat-tab-red{background:#ff2040 !important;color:#fff !important;border-radius:4px;padding:6px 0;text-align:center;font-family:Orbitron,monospace;font-size:13px;letter-spacing:2px;}
input, textarea{color:#e8f1ff !important;}
audio, iframe{border-radius:8px;box-shadow:0 0 18px rgba(0,212,255,0.25);}
section[data-testid="stSidebar"]{display:none !important;}
.topbar{display:flex;align-items:center;justify-content:space-between;padding:10px 8px;border-bottom:1px solid rgba(0,212,255,0.3);background:rgba(5,7,13,0.7);}
.topbar b{font-family:Orbitron,monospace;color:#00d4ff;letter-spacing:2px;}
.nav{display:flex;gap:18px;font-family:Orbitron,monospace;font-size:13px;color:#8aa4bd;}
.nav .on{color:#00d4ff;border-bottom:2px solid #00d4ff;}
.hud{background:rgba(8,15,26,0.9);border:1px solid rgba(0,212,255,0.35);border-radius:12px;padding:12px;box-shadow:0 0 24px rgba(0,212,255,0.12);}
.ht{color:#00d4ff;font-family:Orbitron,monospace;font-size:12px;letter-spacing:3px;text-transform:uppercase;margin-bottom:8px;}
.hr{display:flex;justify-content:space-between;padding:5px 0;border-bottom:1px solid rgba(0,212,255,0.12);font-size:14px;}
.navitem{display:flex;justify-content:space-between;padding:7px 10px;border-radius:8px;font-size:15px;}
.navitem.on{background:rgba(0,212,255,0.14);border:1px solid rgba(0,212,255,0.4);color:#00d4ff;}
.badge{background:#00d4ff;color:#05070d;border-radius:999px;padding:1px 8px;font-size:12px;font-weight:700;}
.chatbox{height:360px;overflow-y:auto;padding:8px;}
.chatbox::-webkit-scrollbar{width:8px;} .chatbox::-webkit-scrollbar-thumb{background:rgba(0,212,255,0.55);border-radius:999px;}
.heybar{display:flex;align-items:center;gap:10px;background:rgba(5,7,13,0.9);border:1px solid rgba(0,212,255,0.4);border-radius:999px;padding:8px 8px 8px 22px;margin-top:8px;}
.heybar input{flex:1;background:transparent;border:none;outline:none;color:#e8f1ff;font-size:17px;}
.micbtn{background:#ff2040;color:#fff;border:none;border-radius:50%;width:52px;height:52px;font-size:20px;box-shadow:0 0 22px rgba(255,32,64,0.6);}
.taskrow{display:flex;justify-content:space-between;padding:7px 0;border-bottom:1px solid rgba(0,212,255,0.12);font-size:14px;}
.qa{display:flex;align-items:center;gap:10px;padding:9px 10px;border:1px solid rgba(0,212,255,0.25);border-radius:10px;margin:6px 0;background:rgba(0,212,255,0.06);font-size:15px;}
</style>
"""


# =====================================================================
# MOBILE EXPERIENCE — phones & tablets
# - Auto-detected from the browser User-Agent; override with ?view=mobile
#   or ?view=desktop (the "Desktop version" button in mobile Settings).
# - Dashboard hub + focused pages routed through ?page=... so every card
#   opens its own page and the browser back button works.
# - Phone hardware (mic, camera, speaker) does the capture/playback locally;
#   replies use the fastest OpenRouter path for quick, accurate answers.
# =====================================================================

MOBILE_PAGES = ("home", "chat", "voice", "camera", "media", "tasks", "weather", "system", "models", "memory", "settings")

MOBILE_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Orbitron:wght@500;700;900&family=Rajdhani:wght@400;600;700&display=swap');
:root { --jcyan:#00d4ff; --jgreen:#00ffb3; --jamber:#ffb020; --jred:#ff3355; --jdeep:#020914; }
html, body { background:#01060f !important; height:100%; overflow:hidden; }
.stApp, [data-testid="stAppViewContainer"], [data-testid="stMain"] {
  max-width: 560px !important; width: 100% !important; margin: 0 auto !important;
  height: 100vh !important; height: 100dvh !important;
  max-height: 100vh !important; max-height: 100dvh !important;
  min-height: 100vh !important; min-height: 100dvh !important;
  overflow: hidden !important; position: fixed; top: 0; left: 50%; transform: translateX(-50%);
}
.stApp {
  background:
    radial-gradient(900px 500px at 50% -10%, rgba(0,120,255,.20), transparent 65%),
    radial-gradient(700px 480px at 100% 30%, rgba(0,255,179,.07), transparent 60%),
    radial-gradient(700px 480px at 0% 80%, rgba(0,100,255,.08), transparent 60%),
    #01060f !important;
}
.stApp::before {
  content:''; position:fixed; inset:0; z-index:9997; pointer-events:none;
  background: repeating-linear-gradient(0deg, rgba(0,212,255,.035) 0 1px, transparent 1px 4px);
  mix-blend-mode: screen;
}
.stApp::after {
  content:''; position:fixed; inset:0; z-index:9996; pointer-events:none;
  background: radial-gradient(ellipse at center, transparent 55%, rgba(0,0,0,.55) 100%);
}
[data-testid="stMainBlockContainer"], .block-container {
  padding: 8px 12px 18px 12px !important; max-width: 100% !important; width: 100% !important;
  height: 100vh !important; height: 100dvh !important;
  max-height: 100vh !important; max-height: 100dvh !important;
  min-height: 100vh !important; min-height: 100dvh !important;
  overflow-y: auto !important; overflow-x: hidden !important;
  -webkit-overflow-scrolling: touch;
}
[data-testid="stHeader"], header, footer, [data-testid="stSidebar"] { display:none !important; }
h1,h2,h3,h4 { font-family:'Rajdhani','Segoe UI',sans-serif !important; color:#eaf6ff !important; }
.stButton > button, .stFormSubmitButton > button {
  min-height: 46px !important; border-radius: 12px !important;
  font-size: 15px !important; font-weight: 700 !important;
  border:1px solid rgba(0,212,255,.35) !important;
  background:linear-gradient(135deg, rgba(0,80,140,.35), rgba(0,30,60,.55)) !important;
  color:#bdf3ff !important;
  box-shadow:inset 0 0 18px rgba(0,150,255,.08);
  transition: all 0.15s ease;
}
.stButton > button:hover { border-color:var(--jcyan) !important; box-shadow:0 0 20px rgba(0,212,255,.28) !important; transform: scale(1.02); }
.stButton > button:active { transform: scale(0.98); }
.stTextInput input, .stNumberInput input, .stTextArea textarea, .stChatInput textarea { font-size: 16px !important; }
.stTextInput input, .stTextArea textarea {
  background:rgba(4,18,34,.9) !important; border-color:rgba(0,212,255,.3) !important; color:#e8f7ff !important;
}
[data-testid="stChatMessage"] { padding: 8px 12px !important; border-radius: 16px !important;
  background: linear-gradient(145deg, rgba(8,28,50,.95), rgba(3,12,26,.98)) !important;
  border: 1px solid rgba(0,212,255,0.2) !important; margin-bottom: 8px !important;
  box-shadow: inset 0 0 26px rgba(0,120,255,.05); max-width: 85%; }
[data-testid="stChatMessage"] [data-testid^="stChatMessageAvatar"] { display: none !important; }
[data-testid="stChatMessage"][data-testid*="user"] { margin-left: auto; background: linear-gradient(145deg, rgba(0,60,100,.95), rgba(0,40,80,.98)) !important; border-color: rgba(0,255,179,0.25) !important; }
[data-testid="stChatInput"] > div { border-color: rgba(0,212,255,0.35) !important; background:rgba(4,18,34,.98) !important; }
[data-testid="stChatInput"]:focus-within > div { border-color: #00d4ff !important; box-shadow: 0 0 0 1px rgba(0,212,255,0.5), 0 0 24px rgba(0,212,255,.2) !important; }
[data-testid="stChatInputSubmitButton"] { color: #00d4ff !important; }
[data-testid="stChatMessageContent"] { font-size: 14px !important; color:#dceeff !important; line-height: 1.5; }
[data-testid="stBottom"] > div {
  background: transparent !important;
  padding: 0 !important;
  border-top: none !important;
}
.stChatInput textarea { border-radius: 24px !important; min-height: 48px !important; }
[data-testid="stCameraInput"] { width:100% !important; max-width:100% !important; height:auto !important; max-height:none !important; }
[data-testid="stCameraInput"] video, [data-testid="stCameraInput"] img, [data-testid="stCameraInput"] canvas {
  width:100% !important; height:auto !important; max-width:100% !important; max-height:60vh !important; object-fit:cover !important;
  border-radius:14px !important; border:1px solid rgba(0,212,255,.3) !important;
}
[data-testid="stAudioInput"] { width:100% !important; }
[data-testid="stMetric"] { background:rgba(5,22,40,.8); border:1px solid rgba(0,212,255,.2); border-radius:12px; padding:8px 10px; }
[data-testid="stExpander"] { border:1px solid rgba(0,212,255,.22) !important; border-radius:12px !important; background:rgba(4,18,34,.6) !important; }

/* ===== JARVIS markup styles (used by the Python pages) ===== */
.mhdr { display:flex; align-items:center; justify-content:space-between; gap:8px;
  padding: 6px 2px 10px; border-bottom: 1px solid rgba(0,212,255,0.28); margin-bottom: 10px; }
.mhdr-left { display:flex; align-items:center; gap:9px; min-width:0; }
.mlogo { font-family:Orbitron,monospace; color:#dffcff; font-weight:900; letter-spacing:2.5px;
  font-size:17px; text-shadow:0 0 12px rgba(0,212,255,.95), 0 0 30px rgba(0,120,255,.55); white-space:nowrap; }
.mlogo i { color:var(--jcyan); font-style:normal; animation:corepulse 2.4s infinite; display:inline-block; }
.msub { font-size:9px; letter-spacing:2.6px; color:#5f8fb0; text-transform:uppercase; }
.mclock { font-family:Orbitron,monospace; font-size:15px; font-weight:800; color:#bdf3ff; letter-spacing:1px; line-height:1.05; }
.mchip { font-size:10px; letter-spacing:1.2px; color:#00ffb3; background:rgba(0,255,179,.08);
  border:1px solid rgba(0,255,179,.38); padding:3px 8px; border-radius:999px; white-space:nowrap;
  box-shadow:0 0 14px rgba(0,255,179,.12); display:inline-block; }
.mchip.think { color:#ffb020; border-color:rgba(255,176,32,.6); background:rgba(255,176,32,.1); box-shadow:0 0 16px rgba(255,176,32,.18); }
.mchip.listen { color:#00d4ff; border-color:rgba(0,212,255,.6); background:rgba(0,212,255,.1); }
.mtitle { font-family:Orbitron,monospace; color:#e8f1ff; font-size:15px; letter-spacing:2px; margin:2px 0 8px; text-transform:uppercase; }
.mk { font-size:15px; font-weight:800; color:#e8f1ff; }
.ms { font-size:12px; color:#8aa4bd; min-height:16px; }
.mbig { font-size:44px; font-weight:900; color:#00d4ff; line-height:1.05; text-shadow:0 0 18px rgba(0,212,255,.55); font-family:Orbitron,monospace; }
.mnote { font-size:12px; color:#8aa4bd; }
.mrow { display:flex; justify-content:space-between; gap:8px; padding:8px 0; border-bottom:1px solid rgba(0,212,255,.12); font-size:14px; color:#cfe7f8; }
.mrow:last-child { border-bottom:none; }
.hud { background:rgba(8,24,42,.85); border:1px solid rgba(0,212,255,.3); border-radius:14px; padding:14px; margin-bottom:10px; }
.ht { color:#00d4ff; font-family:Orbitron,monospace; font-size:11px; letter-spacing:3px; text-transform:uppercase; margin-bottom:8px; }

/* arc reactor */
.mreactor-wrap { position:relative; height:262px; display:flex; align-items:center; justify-content:center; margin:2px 0; }
.mreactor { position:relative; width:250px; height:250px; border-radius:50%; transition: transform .12s ease; }
.mring { position:absolute; border-radius:50%; border:1px solid rgba(0,212,255,.32); }
.r1 { inset:0; border-style:dashed; border-color:rgba(0,212,255,.42); animation:jspin 28s linear infinite; }
.r2 { inset:10px; border-top-color:var(--jgreen); border-right-color:rgba(0,120,255,.15); border-bottom-color:var(--jcyan); border-left-color:rgba(0,120,255,.15); animation:jspinr 14s linear infinite; }
.r3 { inset:24px; border-left-color:var(--jcyan); border-right-color:rgba(0,212,255,.08); border-top-color:rgba(0,255,179,.5); animation:jspin 9s linear infinite; }
.r4 { inset:38px; border:1px dashed rgba(0,255,179,.35); animation:jspinr 36s linear infinite; }
.ticks { position:absolute; inset:2px; border-radius:50%; opacity:.65;
  background: repeating-conic-gradient(from 0deg, rgba(0,212,255,.75) 0deg 1.1deg, transparent 1.1deg 9deg);
  -webkit-mask: radial-gradient(circle, transparent 62%, #000 63%, #000 67%, transparent 68%);
  mask: radial-gradient(circle, transparent 62%, #000 63%, #000 67%, transparent 68%);
  animation:jspin 60s linear infinite; }
.mglow { position:absolute; inset:52px; border-radius:50%;
  background: radial-gradient(circle, rgba(0,212,255,.30) 0%, rgba(0,150,255,.10) 42%, transparent 70%);
  filter:blur(8px); animation:corepulse 3s ease-in-out infinite; }
.mcoil { position:absolute; inset:64px; border-radius:50%; border:2px solid rgba(0,212,255,.75);
  box-shadow: inset 0 0 24px rgba(0,212,255,.75), 0 0 34px rgba(0,212,255,.5);
  animation:corepulse 2.2s ease-in-out infinite; }
.mcore-inner { position:absolute; inset:78px; border-radius:50%; display:flex; flex-direction:column;
  align-items:center; justify-content:center; text-align:center; z-index:3;
  background: radial-gradient(circle, rgba(2,9,20,.92) 0%, rgba(2,9,20,.55) 62%, transparent 72%); }
.mtime { font-family:Orbitron,monospace; font-size:29px; font-weight:900; color:#f2ffff; line-height:1;
  text-shadow:0 0 12px rgba(0,212,255,.95), 0 0 28px rgba(0,120,255,.6); }
.mdate { margin-top:4px; font-size:10px; color:#bdf3ff; letter-spacing:1.4px; text-transform:uppercase; }
.mgreet { margin-top:3px; font-size:9px; color:#7fb7d8; letter-spacing:2px; text-transform:uppercase; }
.mleds { display:flex; align-items:center; justify-content:center; gap:6px; flex-wrap:wrap; margin:2px 0 12px; }
.mled { font-size:9px; letter-spacing:1px; color:#8fb8d4; border:1px solid rgba(0,212,255,.22);
  background:rgba(0,60,110,.18); border-radius:999px; padding:3px 8px; text-transform:uppercase; }
.mled b { color:var(--jgreen); font-weight:800; }
.mled.warn b { color:var(--jamber); }

/* launcher tiles */
[class*="st-key-mtile_"] { position:relative; border:1px solid rgba(0,212,255,.28); border-radius:16px;
  background: linear-gradient(145deg, rgba(8,32,58,.92), rgba(3,12,26,.96));
  box-shadow: inset 0 0 28px rgba(0,120,255,.07), 0 0 18px rgba(0,150,255,.06);
  padding: 10px 12px; min-height: 88px; overflow:hidden;
  clip-path: polygon(13px 0, 100% 0, 100% calc(100% - 13px), calc(100% - 13px) 100%, 0 100%, 0 13px);
  transition: box-shadow .2s, border-color .2s; }
[class*="st-key-mtile_"]:before { content:''; position:absolute; inset:0; pointer-events:none;
  background: linear-gradient(120deg, transparent 20%, rgba(0,212,255,.10) 48%, transparent 72%);
  transform: translateX(-120%); animation: jsheen 6s ease-in-out infinite; }
[class*="st-key-mtile_"]:hover { border-color: rgba(0,212,255,.75); box-shadow: 0 0 26px rgba(0,212,255,.22), inset 0 0 30px rgba(0,212,255,.10); }
[class*="st-key-mtile_"] .stButton > button { position:absolute; inset:0; opacity:0; z-index:20;
  min-height:100% !important; border-radius:16px !important; }
[class*="st-key-mtile_"] [data-testid="stMarkdownContainer"] { position:relative; z-index:2; }
/* Mobile tiles: whole card is clickable and bigger */
[class*="st-key-mtile_"] { min-height: 96px !important; position: relative !important; padding: 4px !important; }
[class*="st-key-mtile_"] button[type="button"] { position: absolute !important; inset: 0 !important; width: 100% !important; height: 100% !important; min-height: 96px !important; border-radius: 12px !important; font-size: 13px !important; touch-action: manipulation !important; }
[class*="st-key-mtile_"] .mtile-corner { display: none !important; }
[class*="st-key-mtile_"] .mtile-icon { font-size: 24px !important; margin-top: 6px !important; }
[class*="st-key-mtile_"] .mtile-title { margin-top: 6px !important; font-size: 13px !important; }
[class*="st-key-mtile_"] .mtile-sub { font-size: 10px !important; }
[class*="st-key-m_chat_bar"] button { touch-action: manipulation !important; }
.mtile-icon { font-size:22px; line-height:1; filter: drop-shadow(0 0 8px rgba(0,212,255,.5)); }
.mtile-title { margin-top:4px; font-family:Orbitron,monospace; font-size:12px; font-weight:800; letter-spacing:1.2px; color:#e8f7ff; text-transform:uppercase; }
.mtile-sub { margin-top:2px; font-size:10px; color:#7fa8c4; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.mtile-corner { position:absolute; right:8px; top:7px; font-size:9px; color:var(--jcyan); opacity:.7; z-index:1; }
.st-key-m_home_grid [data-testid="stHorizontalBlock"] { flex-wrap:nowrap !important; gap:8px !important; width:100% !important; }
.st-key-m_home_grid [data-testid="stColumn"] { min-width:0 !important; flex:1 1 0 !important; width:auto !important; max-width:calc(50% - 4px) !important; }
.st-key-m_home_grid [data-testid="stVerticalBlockBorderWrapper"] { min-width:0 !important; }

/* boot overlay */
.mboot { position:fixed; inset:0; z-index:99999; background:#01050c; display:flex; flex-direction:column;
  align-items:center; justify-content:center; gap:14px; pointer-events:none;
  animation: jbootout 2.8s ease forwards; }
.mboot-core { width:96px; height:96px; border-radius:50%; border:2px solid var(--jcyan);
  box-shadow: 0 0 40px rgba(0,212,255,.9), inset 0 0 34px rgba(0,212,255,.55);
  display:flex; align-items:center; justify-content:center; font-family:Orbitron,monospace;
  color:#eaffff; font-size:22px; font-weight:900; animation: corepulse 1.1s ease-in-out infinite; }
.mboot-title { font-family:Orbitron,monospace; color:#dffcff; letter-spacing:6px; font-size:15px;
  text-shadow:0 0 18px rgba(0,212,255,.9); }
.mboot-sub { font-size:9px; letter-spacing:3px; color:#5f9fc0; text-transform:uppercase; }
.mboot-bar { width:230px; height:4px; background:rgba(0,212,255,.14); border-radius:999px; overflow:hidden;
  border:1px solid rgba(0,212,255,.18); }
.mboot-bar i { display:block; height:100%; width:0; background:linear-gradient(90deg,var(--jgreen),var(--jcyan));
  box-shadow:0 0 12px var(--jcyan); animation: jloadbar 2.35s ease forwards; }
.mboot-grid { position:absolute; inset:0; opacity:.18;
  background-image: linear-gradient(rgba(0,212,255,.18) 1px, transparent 1px), linear-gradient(90deg, rgba(0,212,255,.18) 1px, transparent 1px);
  background-size: 34px 34px; -webkit-mask: radial-gradient(circle, #000, transparent 72%); }

/* voice-reactive states */
body.jarvis-listening .mcoil { border-color: var(--jgreen); box-shadow: inset 0 0 30px rgba(0,255,179,.8), 0 0 46px rgba(0,255,179,.55); animation-duration:1.2s; }
body.jarvis-listening .r2 { animation-duration:4s; border-top-color:var(--jgreen); }
body.jarvis-thinking .r3 { animation-duration:1.6s; border-left-color:var(--jamber); }
body.jarvis-thinking .mchip { color:var(--jamber); }
body.jarvis-speaking .mcoil { border-color:#8fe8ff; box-shadow: inset 0 0 40px rgba(0,212,255,.95), 0 0 60px rgba(0,212,255,.7); }
body.jarvis-speaking .mglow { opacity:1; transform:scale(1.08); }
body.jv-tick .mreactor { transform:scale(1.018); }
body.jv-tick .mcoil { box-shadow: inset 0 0 44px rgba(180,250,255,.95), 0 0 70px rgba(0,212,255,.8); }

/* mic + camera helpers */
.mic-btn { width: 64px; height: 64px; border-radius: 50%; border: 2px solid rgba(0,212,255,.4); background: linear-gradient(135deg, rgba(0,80,140,.5), rgba(0,30,60,.7)); display: flex; align-items: center; justify-content: center; cursor: pointer; touch-action: none; -webkit-tap-highlight-color: transparent; }
.mic-btn.recording { background: linear-gradient(135deg, #ff3355, #cc0033); border-color: #ff3355; box-shadow: 0 0 30px rgba(255,51,85,.8); animation: micPulse 0.5s ease-in-out infinite; }
@keyframes micPulse { 0%,100% { box-shadow: 0 0 30px rgba(255,51,85,.8), inset 0 0 20px rgba(255,51,85,.4); } 50% { box-shadow: 0 0 50px rgba(255,51,85,1), inset 0 0 30px rgba(255,51,85,.6); } }
@keyframes micSpin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }

/* Animations */
@keyframes jspin { to { transform: rotate(360deg); } }
@keyframes jspinr { to { transform: rotate(-360deg); } }
@keyframes corepulse { 0%,100% { opacity:.85; transform:scale(1); } 50% { opacity:1; transform:scale(1.035); } }
@keyframes jsheen { 0%,55% { transform:translateX(-120%); } 75%,100% { transform:translateX(120%); } }
@keyframes jloadbar { 0% { width:0; } 60% { width:72%; } 100% { width:100%; } }
@keyframes jbootout { 0%,78% { opacity:1; visibility:visible; } 100% { opacity:0; visibility:hidden; } }
@media (prefers-reduced-motion: reduce) { .r1,.r2,.r3,.r4,.ticks,.glow,.coil,.boot-core { animation:none !important; } .home-tile:before { animation:none !important; } .boot-overlay { animation: jbootout 1s ease forwards; } }

/* Models box */
.st-key-m_models_box { background:rgba(8,32,64,0.92) !important; border:1.5px solid rgba(0,150,255,0.65) !important; border-radius:16px !important; padding:12px !important; box-shadow:0 0 22px rgba(0,140,255,0.18) !important; }

/* Hide Streamlit native chat input on merged page */
[data-testid="stChatInput"] { display: none !important; }

/* Zero-layout utility components: keep them mounted but out of the flow */
.st-key-m_sfx_comp, .st-key-m_pwa, .st-key-m_clock_comp, .st-key-m_tts {
  position: absolute !important; left: -9999px !important; top: 0 !important;
  width: 1px !important; height: 1px !important; overflow: hidden !important;
  margin: 0 !important; padding: 0 !important;
}
/* The two global <style> blocks must not occupy layout space */
[data-testid="stMainBlockContainer"] > [data-testid="stVerticalBlock"] > .stElementContainer:has(style) {
  display: none !important;
}

/* ===== Chat page: fill the viewport, scroll messages, pin input bar ===== */
[data-testid="stMainBlockContainer"]:has(#m-chat-flag) {
  display: flex !important; flex-direction: column !important;
}
[data-testid="stMainBlockContainer"]:has(#m-chat-flag) > [data-testid="stVerticalBlock"] {
  flex: 1 1 auto !important; min-height: 0 !important;
}
[data-testid="stMainBlockContainer"]:has(#m-chat-flag) [data-testid="stLayoutWrapper"]:has(> .st-key-m_chat_scroll) {
  flex: 1 1 auto !important; min-height: 0 !important; height: auto !important;
}
.st-key-m_chat_scroll {
  flex: 1 1 auto !important;
  height: 100% !important;
  max-height: none !important;
  min-height: 160px !important;
  overflow-y: auto !important; overflow-x: hidden !important;
  overscroll-behavior: contain;
  padding: 4px 6px 8px 4px !important;
  border: 1px solid rgba(0,212,255,.14) !important;
  border-radius: 14px !important;
  background: rgba(2,10,22,.35) !important;
}
.st-key-m_chat_scroll::-webkit-scrollbar { width: 5px; }
.st-key-m_chat_scroll::-webkit-scrollbar-track { background: transparent; }
.st-key-m_chat_scroll::-webkit-scrollbar-thumb { background: rgba(0,212,255,.4); border-radius: 3px; }
.st-key-m_chat_scroll [data-testid="stChatMessage"] { max-width: 88% !important; }
.st-key-m_chat_scroll [data-testid="stElementContainer"], .st-key-m_chat_scroll .stElementContainer { flex-shrink: 0 !important; }
.st-key-m_chat_scroll > [data-testid="stElementContainer"] { min-height: max-content; }

/* Chat header row: back button + title side by side on phones */
.st-key-m_chat_head [data-testid="stHorizontalBlock"] { flex-wrap: nowrap !important; align-items: center !important; gap: 8px !important; }
.st-key-m_chat_head [data-testid="stColumn"] { width: auto !important; min-width: 0 !important; flex: 1 1 0 !important; }
.st-key-m_chat_head [data-testid="stColumn"]:first-child { flex: 0 0 44px !important; max-width: 44px !important; }
.st-key-m_chat_head [data-testid="stColumn"]:first-child button { min-height: 34px !important; height: 34px !important; padding: 0 !important; font-size: 16px !important; border-radius: 10px !important; }
.st-key-m_chat_head .mtitle { margin: 0 !important; }

/* Input bar: keep text + send + mic on ONE row (Streamlit stacks columns on phones) */
.st-key-m_chat_bar [data-testid="stHorizontalBlock"] { flex-wrap: nowrap !important; align-items: center !important; gap: 8px !important; }
.st-key-m_chat_bar [data-testid="stHorizontalBlock"] > [data-testid="stColumn"] { width: auto !important; min-width: 0 !important; flex: 1 1 0 !important; }
.st-key-m_chat_bar > div > [data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:last-child { flex: 0 0 76px !important; max-width: 76px !important; }
.st-key-m_chat_bar [data-testid="stForm"] [data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:last-child { flex: 0 0 52px !important; max-width: 52px !important; }
.st-key-m_chat_bar [data-testid="stForm"] { width: 100% !important; }
.st-key-m_chat_bar { position: sticky !important; bottom: -6px !important; z-index: 80 !important; margin-top: 4px !important;
  padding: 6px 0 calc(6px + env(safe-area-inset-bottom)) 0 !important;
  background: linear-gradient(180deg, rgba(2,9,20,.72), rgba(2,9,20,.99) 40%) !important;
  border-top: 1px solid rgba(0,212,255,.25) !important; backdrop-filter: blur(14px) !important; }
.st-key-m_chat_bar [data-testid="stForm"] { border: none !important; padding: 0 !important; background: transparent !important; }
.st-key-m_chat_bar .stTextInput input { min-height: 46px !important; border-radius: 23px !important; }
.st-key-m_chat_bar .stFormSubmitButton > button { min-height: 46px !important; width: 46px !important; border-radius: 50% !important; font-size: 18px !important; padding: 0 !important; }

/* Bigger, phone-friendly camera */
[data-testid="stCameraInput"] video, [data-testid="stCameraInput"] img {
  max-height: 66vh !important;
}
[data-testid="stCameraInput"] button {
  min-height: 54px !important; font-size: 15px !important; font-weight: 800 !important;
  border-radius: 14px !important; border: 1.5px solid rgba(0,212,255,.55) !important;
  background: linear-gradient(135deg, rgba(0,90,150,.55), rgba(0,30,60,.9)) !important;
  color: #dffbff !important;
}
[data-testid="stCameraInput"] button:hover { box-shadow: 0 0 24px rgba(0,212,255,.35) !important; }
@media (max-height: 700px) {
  .st-key-m_chat_scroll { min-height: 160px !important; }
}

/* Sources expander */
.sources-expander { border: 1px solid rgba(0,212,255,.2) !important; border-radius: 12px !important; background: rgba(4,18,34,.6) !important; margin-top: 8px; }
</style>
"""


def _qp_str(name: str, default: str = "") -> str:
    try:
        v = st.query_params.get(name, default)
    except Exception:
        return default
    if isinstance(v, list):
        return (v[0] if v else default) or default
    return (v or default)


def _is_mobile_view() -> bool:
    if os.getenv("JARVIS_FORCE_MOBILE") == "1":
        return True
    view = _qp_str("view", "").strip().lower()
    if view == "mobile":
        return True
    if view == "desktop":
        return False
    try:
        ua = st.context.headers.get("User-Agent", "") or ""
    except Exception:
        ua = ""
    return bool(re.search(r"Android|iPhone|iPad|iPod|Mobile|Windows Phone|IEMobile|Opera Mini", ua, re.I))


@st.cache_data(ttl=600, show_spinner=False)
def get_weather_cached() -> dict:
    return get_weather()


# --- Hands-free voice listener (CCv2: runs in the phone browser, reports to Python) ---
_MOBILE_HF_JS = r"""
export default function (component) {
  const { data, parentElement, setTriggerValue } = component
  const statusEl = parentElement.querySelector('#hf-status')
  const dot = parentElement.querySelector('#hf-dot')
  if (!statusEl || !dot) return
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition
  if (!SR) {
    statusEl.textContent = 'Hands-free is not supported in this browser — use tap-to-talk above.'
    dot.style.background = '#ff2040'
    return
  }
  const enabled = !!(data && data.enabled)
  const wake = ((data && data.wake) || 'jarvis').toLowerCase()
  const requireWake = data ? data.requireWake !== false : true
  const lang = (data && data.lang) || 'en-US'
  const G = window.__jarvisHF || (window.__jarvisHF = {})
  const W = (function () { try { if (window.parent && window.parent.document) return window.parent } catch (e) {} return window })()
  if (!G.rec) {
    const rec = new SR()
    rec.continuous = true
    rec.interimResults = true
    rec.lang = lang
    G.rec = rec
    G.running = false
    G.enabled = false
    rec.onstart = function () {
      G.running = true
      statusEl.textContent = 'Listening… say “' + wake + ' …”'
      dot.style.background = '#00ffb3'
      if (G.enabled) document.body.classList.add('jarvis-listening')
    }
    rec.onend = function () {
      G.running = false
      if (!G.enabled) { document.body.classList.remove('jarvis-listening'); return }
      setTimeout(function restart() {
        if (!G.enabled) return
        try { if (W.__jarvisSpeaking) { setTimeout(restart, 1200); return } } catch (e) {}
        try { rec.start() } catch (e) {}
      }, 400)
    }
    rec.onerror = function (e) {
      G.running = false
      if (e.error === 'not-allowed' || e.error === 'service-not-allowed') {
        G.enabled = false
        document.body.classList.remove('jarvis-listening')
        statusEl.textContent = 'Mic permission denied — allow the mic or use tap-to-talk.'
        dot.style.background = '#ff2040'
      } else if (e.error === 'no-speech' || e.error === 'aborted') {
        statusEl.textContent = 'Listening… say “' + wake + ' …”'
      } else {
        statusEl.textContent = 'Voice error: ' + e.error
      }
    }
    rec.onresult = function (ev) {
      let interim = ''
      for (let i = ev.resultIndex; i < ev.results.length; i++) {
        const r = ev.results[i]
        const t = ((r[0] && r[0].transcript) || '').trim()
        if (!t) continue
        if (r.isFinal) {
          var nowMs = Date.now()
          // Never react to JARVIS's own voice coming back through the phone mic.
          try {
            if (W.__jarvisSpeaking || (W.__jarvisSpeechEnd && (nowMs - W.__jarvisSpeechEnd) < 2400)) {
              statusEl.textContent = '…'
              continue
            }
          } catch (e) {}
          var cmd = t
          if (requireWake) {
            var low = t.toLowerCase()
            var wx = wake.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
            var mm = low.match(new RegExp('^(?:hey\\s+)?' + wx + '\\b[\\s,;:.!?\\-]*'))
            if (!mm) {
              statusEl.textContent = 'Heard “' + t + '” — say “' + wake + ' …”'
              continue
            }
            cmd = t.slice(mm[0].length).trim().replace(/^[\s,\.\!\?:\-]+/, '')
            if (!cmd) cmd = 'hello'
          }
          // Ignore a repeated transcript (echo / recognizer restart).
          if (G.lastCmd === cmd && (nowMs - (G.lastCmdTs || 0)) < 6000) {
            statusEl.textContent = '…'
            continue
          }
          G.lastCmd = cmd
          G.lastCmdTs = nowMs
          statusEl.textContent = 'Heard: "' + cmd + '"'
          if (window.__jarvisSFX) window.__jarvisSFX.play('wake')
          // STOP any ongoing TTS when wake word is recognized
          try { if (window.__jarvisTTS && window.__jarvisTTS.bc) window.__jarvisTTS.bc.postMessage('STOP') } catch (x) {}
          try { if (W.__jarvisTTS && W.__jarvisTTS.bc) W.__jarvisTTS.bc.postMessage('STOP') } catch (x) {}
          setTriggerValue('heard', cmd)
        } else {
          interim = t
        }
      }
      if (interim) statusEl.textContent = '…' + interim
    }
  } else {
    G.rec.lang = lang
  }
  G.enabled = enabled
  if (enabled && !G.running) { try { G.rec.start() } catch (e) {} }
  if (!enabled && G.running) { try { G.rec.stop() } catch (e) {} }
  if (!enabled) {
    statusEl.textContent = 'Hands-free is off — turn on the toggle above.'
    dot.style.background = '#3a5a75'
    document.body.classList.remove('jarvis-listening')
  }
  return function () {
    try { G.enabled = false; if (G.rec && G.running) G.rec.stop() } catch (e) {}
    G.rec = null
    G.running = false
    document.body.classList.remove('jarvis-listening')
  }
}
"""

try:
    _MOBILE_HF = _ccv2_component(
        "jarvis_mobile_hands_free",
        '''<div style="display:flex;align-items:center;gap:10px;padding:10px 12px;border:1px solid rgba(0,212,255,.3);border-radius:12px;background:rgba(6,24,39,.9);"><span id="hf-dot" style="width:10px;height:10px;border-radius:50%;background:#3a5a75;flex:0 0 auto;"></span><span id="hf-status" style="font-size:12px;color:#8aa4bd;">Hands-free is off.</span></div>''',
        _MOBILE_HF_JS,
    )
except Exception:
    _MOBILE_HF = None


# --- Phone TTS (CCv2: speechSynthesis runs on the device) ---
_MOBILE_TTS_JS = r"""
export default function (component) {
  const { data, parentElement } = component
  const btn = parentElement.querySelector('#spk')
  const stt = parentElement.querySelector('#tst')
  if (!btn || !stt) return
  const text = (data && data.text) || ''
  const token = (data && data.token) || ''
  const auto = !!(data && data.auto)
  const audioB64 = (data && data.audio) || ''
  const lang = (data && data.lang) || (window.__jarvisHold && window.__jarvisHold.lang) || 'en-US'
  btn.style.cssText = 'background:rgba(0,212,255,0.10);border:1px solid rgba(0,212,255,0.45);color:#bdf3ff;border-radius:10px;padding:5px 10px;font-size:11px;font-weight:700;'
  stt.style.cssText = 'display:block;color:#8aa4bd;font-size:10px;margin-top:2px;'
  const hasSynth = ('speechSynthesis' in window)

  // Parent window: it survives iframe remounts and Streamlit reconnects.
  var W = window
  try { if (window.parent && window.parent.document) W = window.parent } catch (e) {}
  const G = W.__jarvisTTS || (W.__jarvisTTS = { audio: null, token: '', playing: false, bc: null, timer: null, srcToken: '', startedAt: 0 })

  function noteSpeaking(on) {
    try { W.__jarvisSpeaking = !!on } catch (e) {}
    if (!on) { try { W.__jarvisSpeechEnd = Date.now() } catch (e) {} }
    try { if (G.bc) G.bc.postMessage(on ? 'SPEAKING_START' : 'SPEAKING_END') } catch (e) {}
  }
  function keyFor(t) { return 'jv_spoken_' + t }
  function alreadyPlayed(t) {
    if (!t) return false
    try { if (W.sessionStorage && W.sessionStorage.getItem(keyFor(t)) === '1') return true } catch (e) {}
    try {
      var ts = parseInt((W.localStorage && W.localStorage.getItem(keyFor(t))) || '0', 10)
      if (ts && (Date.now() - ts) < 43200000) return true
    } catch (e) {}
    return false
  }
  function markPlayed(t) {
    if (!t) return
    try { if (W.sessionStorage) W.sessionStorage.setItem(keyFor(t), '1') } catch (e) {}
    try { if (W.localStorage) W.localStorage.setItem(keyFor(t), String(Date.now())) } catch (e) {}
  }
  function unmarkPlayed(t) {
    if (!t) return
    try { if (W.sessionStorage) W.sessionStorage.removeItem(keyFor(t)) } catch (e) {}
    try { if (W.localStorage) W.localStorage.removeItem(keyFor(t)) } catch (e) {}
  }
  function clearTimer() { try { if (G.timer) { clearTimeout(G.timer); G.timer = null } } catch (e) {} }
  function hideChip() { try { parentElement.style.display = 'none' } catch (e) {} }
  function pickVoice(userLang) {
    const vs = window.speechSynthesis.getVoices() || []
    if (userLang) {
      const norm = function (v) { return (v || '').toLowerCase().replace('_', '-') }
      const exact = vs.find(function (v) { return norm(v.lang) === norm(userLang) })
      if (exact) return exact
      const base = userLang.split('-')[0]
      const pref = vs.find(function (v) { return norm(v.lang).indexOf(base + '-') === 0 })
      if (pref) return pref
    }
    return vs.find(function (v) { return /Guy|David|Daniel|Alex|Google UK English Male/i.test((v.name || '') + ' ' + (v.voiceURI || '')) })
      || vs.find(function (v) { return /^en[-_](US|IN|GB)/i.test(v.lang || '') && /male|guy|david/i.test(v.name || '') })
      || vs.find(function (v) { return (v.lang || '').indexOf('en-US') === 0 })
      || vs.find(function (v) { return (v.lang || '').indexOf('en') === 0 })
      || null
  }
  function stopAll() {
    clearTimer()
    if (G.audio) { try { G.audio.pause() } catch (e) {} try { G.audio.currentTime = 0 } catch (e) {} }
    if (hasSynth) { try { window.speechSynthesis.cancel() } catch (e) {} }
    try { if (W !== window && W.speechSynthesis) W.speechSynthesis.cancel() } catch (e) {}
    G.playing = false
    G.token = ''
    noteSpeaking(false)
  }
  // BroadcastChannel for cross-iframe STOP signals (mic, send, tiles, buttons)
  try {
    if (!G.bc) { G.bc = new W.BroadcastChannel('jarvis_tts'); G.bc.onmessage = function (e) { if (e.data === 'STOP') stopAll() } }
  } catch (e) {}
  function broadcastStop() { try { if (G.bc) G.bc.postMessage('STOP') } catch (e) {} }
  function ensureAudio() {
    if (G.audio) return G.audio
    try { if (W !== window && W.Audio) { G.audio = new W.Audio(); G.audio.setAttribute('playsinline', ''); return G.audio } } catch (e) {}
    return null
  }
  function playAudio() {
    if (!audioB64) return false
    const a = ensureAudio()
    if (!a) return false
    try {
      if (G.playing && G.token === token) return true
      clearTimer()
      try { a.pause() } catch (e) {}
      if (G.srcToken !== token || !a.src) {
        a.src = 'data:audio/mp3;base64,' + audioB64
        G.srcToken = token
        try { a.load() } catch (e) {}
      } else {
        try { a.currentTime = 0 } catch (e) {}
      }
      G.audio = a
      G.playing = true
      G.token = token
      G.startedAt = Date.now()
      a.onplaying = function () { stt.textContent = 'Speaking…'; document.body.classList.add('jarvis-speaking'); hideChip() }
      a.onended = function () { stt.textContent = ''; document.body.classList.remove('jarvis-speaking'); stopAll() }
      a.onerror = function () { document.body.classList.remove('jarvis-speaking'); unmarkPlayed(token); stopAll(); speak() }
      markPlayed(token)
      noteSpeaking(true)
      const p = a.play()
      if (p && p.catch) { p.catch(function () { unmarkPlayed(token); stt.textContent = 'Tap to hear the reply.'; document.body.classList.remove('jarvis-speaking'); stopAll() }) }
      return true
    } catch (e) { unmarkPlayed(token); return false }
  }
  function speak() {
    if (!text || !hasSynth) return
    try {
      clearTimer()
      try { if (G.audio) G.audio.pause() } catch (e) {}
      window.speechSynthesis.cancel()
      const u = new SpeechSynthesisUtterance(text)
      u.rate = 0.97
      u.pitch = 0.95
      u.volume = 1.0
      try { u.lang = lang || 'en-US' } catch (x) {}
      const v = pickVoice(lang)
      if (v) u.voice = v
      u.onstart = function () {
        stt.textContent = 'Speaking…'
        document.body.classList.add('jarvis-speaking')
        if (window.__jarvisSFX) window.__jarvisSFX.play('reply')
        hideChip()
        noteSpeaking(true)
      }
      u.onboundary = function () {
        document.body.classList.remove('jv-tick')
        void document.body.offsetWidth
        document.body.classList.add('jv-tick')
        clearTimeout(window.__jvTick)
        window.__jvTick = setTimeout(function () { document.body.classList.remove('jv-tick') }, 150)
      }
      u.onend = function () { stt.textContent = ''; document.body.classList.remove('jarvis-speaking', 'jv-tick'); noteSpeaking(false); G.playing = false; G.token = '' }
      u.onerror = function () { stt.textContent = 'Tap to hear the reply.'; document.body.classList.remove('jarvis-speaking', 'jv-tick'); noteSpeaking(false); G.playing = false; G.token = '' }
      try { if (window.speechSynthesis) { window.speechSynthesis.resume() } } catch (e) {}
      window.speechSynthesis.speak(u)
      G.playing = true
      G.token = token
      markPlayed(token)
    } catch (e) {
      stt.textContent = 'Tap to hear the reply.'
      G.playing = false
    }
  }
  function play(manual) {
    clearTimer()
    if (!manual) {
      if (token && alreadyPlayed(token)) return
      if (G.playing && G.token === token) return
    }
    if (!playAudio()) speak()
  }
  btn.onclick = function () { broadcastStop(); play(true) }
  try { window.__jarvisTtsPlay = function () { play(true) } } catch (e) {}
  // Auto-play ONLY a just-generated reply, and only if this tab never played that token.
  if (auto && token && !alreadyPlayed(token) && !(G.playing && G.token === token)) {
    G.timer = setTimeout(function () {
      G.timer = null
      if (auto && token && alreadyPlayed(token)) return
      broadcastStop()
      play(false)
    }, 120)
  }
  // Voice list is read on demand; never auto-replay from voiceschanged or pointerdown.
  try {
    document.addEventListener('click', function () { try { if (hasSynth) window.speechSynthesis.resume() } catch (e) {} }, true)
  } catch (e) {}
  // Parent-doc STOP signal listener (from mic, send, tiles, etc.)
  try {
    window.addEventListener('message', function (e) { if (e.data && e.data.type === 'JARVIS_STOP_TTS') stopAll() })
  } catch (e) {}
}
"""

try:
    _MOBILE_TTS = _ccv2_component(
        "jarvis_mobile_tts",
        '''<div><audio id="spk-audio" preload="auto" style="display:none"></audio><button id="spk" type="button">🔊 Voice</button><span id="tst"></span></div>''',
        _MOBILE_TTS_JS,
    )
except Exception:
    _MOBILE_TTS = None


_MOBILE_VOICE_CACHE: dict = {}
_EDGE_BASES = {"en", "hi", "te", "kn", "ta", "ml", "mr", "bn", "gu", "es", "fr", "de", "pt", "ja"}


def _new_tts_id() -> str:
    import uuid
    return uuid.uuid4().hex


def _mobile_tts(text: str, tts_id: str = "") -> None:
    """Speak a reply on the phone with a NATIVE neural voice (Edge) — natural accent,
    human pauses and breathing. Auto-plays ONLY when this message is freshly generated;
    re-renders/reloads never replay old replies. Device TTS only as a last resort."""
    if not text or _MOBILE_TTS is None:
        return
    import hashlib as _hl
    import base64 as _b64m
    _sel = str(st.session_state.get("stt_lang") or "en-US").strip().lower()
    _lang = speech_lang_for(text, _sel)
    voice = voice_for_lang(_lang, st.session_state.get("voice_gender", "auto"), st.session_state.get("voice_choice"))
    fresh = bool(tts_id) and st.session_state.get("_tts_fresh") == tts_id
    if tts_id:
        # Single-use: this message can auto-play at most once, even across remounts.
        st.session_state["_tts_fresh"] = ""
    clean = humanize_for_speech(text, limit=700, lang=_lang)
    if not clean:
        return
    sent = st.session_state.get("_tts_sent")
    if not isinstance(sent, set):
        sent = set()
        st.session_state["_tts_sent"] = sent
    if fresh and tts_id in sent:
        fresh = False
    tok = _hl.md5((clean + "|" + voice + "|" + (tts_id or "old")).encode()).hexdigest()
    b64 = _MOBILE_VOICE_CACHE.get(tok, "")
    if fresh:
        sent.add(tts_id)
        if len(sent) > 120:
            st.session_state["_tts_sent"] = set(list(sent)[-60:])
        st.session_state["_last_tts_ts"] = time.time()
    if fresh and not b64 and _lang_base(_lang) in _EDGE_BASES:
        try:
            b64 = _b64m.b64encode(synthesize_human_speech(text, voice, "auto", lang=_lang)).decode()
        except Exception:
            b64 = ""
        if b64:
            _MOBILE_VOICE_CACHE[tok] = b64
            if len(_MOBILE_VOICE_CACHE) > 60:
                for _k in list(_MOBILE_VOICE_CACHE)[:20]:
                    _MOBILE_VOICE_CACHE.pop(_k, None)
    try:
        _MOBILE_TTS(
            key="m_tts",
            data={"text": clean, "token": tok, "auto": fresh, "lang": _lang or "", "audio": b64},
            height=30,
        )
    except Exception:
        pass


# --- HUD sound design (Web Audio: no files, synthesized sci-fi UI sounds) ---
_MOBILE_SFX_JS = r"""
export default function (component) {
  const { data } = component
  const G = window.__jarvisSFX || (window.__jarvisSFX = {})
  G.enabled = data ? data.enabled !== false : true
  G.volume = (data && typeof data.volume === 'number') ? data.volume : 0.18
  function ctx() {
    if (!G.ctx) { try { G.ctx = new (window.AudioContext || window.webkitAudioContext)() } catch (e) {} }
    if (G.ctx && G.ctx.state === 'suspended') { try { G.ctx.resume() } catch (e) {} }
    return G.ctx
  }
  function noise(dur, start, type, gain, freq1, freq2) {
    const c = ctx(); if (!c) return
    try {
      const buf = c.createBuffer(1, c.sampleRate * dur, c.sampleRate)
      const ch = buf.getChannelData(0)
      for (let i = 0; i < ch.length; i++) ch[i] = Math.random() * 2 - 1
      const ns = c.createBufferSource(); ns.buffer = buf
      const bp = c.createBiquadFilter(); bp.type = type || 'bandpass'; bp.frequency.value = freq1 || 1000; bp.Q.value = 2
      const g = c.createGain()
      g.gain.setValueAtTime(0.0001, c.currentTime + start)
      g.gain.linearRampToValueAtTime(gain || 0.03, c.currentTime + start + 0.01)
      g.gain.exponentialRampToValueAtTime(0.0001, c.currentTime + start + dur)
      ns.connect(bp); bp.connect(g); g.connect(c.destination)
      ns.start(c.currentTime + start); ns.stop(c.currentTime + start + dur + 0.02)
    } catch (e) {}
  }
  function tone(freq, start, dur, type, gain) {
    const c = ctx(); if (!c) return
    try {
      const o = c.createOscillator(), g = c.createGain()
      o.type = type || 'sine'
      o.frequency.setValueAtTime(freq, c.currentTime + start)
      g.gain.setValueAtTime(0.0001, c.currentTime + start)
      g.gain.linearRampToValueAtTime(gain || 0.06, c.currentTime + start + 0.015)
      g.gain.exponentialRampToValueAtTime(0.0001, c.currentTime + start + dur)
      o.connect(g); g.connect(c.destination)
      o.start(c.currentTime + start); o.stop(c.currentTime + start + dur + 0.03)
    } catch (e) {}
  }
  function sweep(f1, f2, dur, start, type, gain) {
    const c = ctx(); if (!c) return
    try {
      const o = c.createOscillator(), g = c.createGain()
      o.type = type || 'sine'
      o.frequency.setValueAtTime(f1, c.currentTime + start)
      o.frequency.exponentialRampToValueAtTime(f2, c.currentTime + start + dur)
      g.gain.setValueAtTime(0.0001, c.currentTime + start)
      g.gain.linearRampToValueAtTime(gain || 0.04, c.currentTime + start + 0.01)
      g.gain.exponentialRampToValueAtTime(0.0001, c.currentTime + start + dur)
      o.connect(g); g.connect(c.destination)
      o.start(c.currentTime + start); o.stop(c.currentTime + start + dur + 0.02)
    } catch (e) {}
  }
  G.play = function (kind) {
    if (!G.enabled) return
    const v = G.volume
    try {
      if (kind === 'boot') { tone(55, 0, .6, 'sine', v * .6); tone(110, .1, .5, 'triangle', v * .35); noise(.7, 0, 'bandpass', v * .18, 200, 8000); tone(1200, .4, .3, 'sine', v * .12); tone(2400, .55, .2, 'sine', v * .06) }
      else if (kind === 'tap') { tone(2400, 0, .03, 'square', v * .12); tone(3200, .015, .02, 'sine', v * .06) }
      else if (kind === 'nav') { noise(.25, 0, 'bandpass', v * .25, 900, 3200); sweep(880, 1320, .18, .08, 'sine', v * .18) }
      else if (kind === 'listen') { sweep(800, 1800, .12, 0, 'sine', v * .16) }
      else if (kind === 'stop') { sweep(1800, 600, .08, 0, 'sine', v * .14) }
      else if (kind === 'back') { noise(.22, 0, 'bandpass', v * .22, 2600, 700); sweep(2600, 700, .35, .05, 'sine', v * .16) }
      else if (kind === 'typing') { tone(1300, 0, .05, 'sine', v * .08) }
      else if (kind === 'send') { tone(520, 0, .05, 'triangle', v * .28); tone(780, .07, .06, 'triangle', v * .2) }
      else if (kind === 'wake') { tone(880, 0, .12, 'sine', v * .25); tone(660, .14, .18, 'sine', v * .2); tone(880, .35, .1, 'sine', v * .08) }
      else if (kind === 'reply') { sweep(300, 700, .15, 0, 'sine', v * .18); tone(1200, .18, .08, 'sine', v * .1) }
      else if (kind === 'error') { tone(180, 0, .2, 'sawtooth', v * .25); tone(120, .12, .25, 'sawtooth', v * .2) }
      else if (kind === 'warp') { sweep(80, 200, .6, 0, 'sawtooth', v * .14); sweep(180, 80, .5, .2, 'sine', v * .12); tone(720, .5, .3, 'sine', v * .08) }
    } catch (e) {}
  }
  function thinkSet(on) {
    try {
      if (on) {
        if (!G.thinkOsc) {
          const c = ctx(); if (c) {
            const o = c.createOscillator(), g = c.createGain()
            o.type = 'sine'; o.frequency.value = 160
            g.gain.value = 0.015
            o.connect(g); g.connect(c.destination)
            o.start(); G.thinkOsc = o; G.thinkG = g
          }
        }
      } else if (G.thinkOsc) {
        try { G.thinkG.gain.exponentialRampToValueAtTime(0.0001, ctx().currentTime + 0.12) } catch (x) {}
        try { G.thinkOsc.stop(ctx().currentTime + 0.2) } catch (x) {}
        G.thinkOsc = null; G.thinkG = null
      }
    } catch (e) {}
  }
  if (!G.bound) {
    G.bound = true
    var _docs = [document]
    try { if (window.parent && window.parent.document && window.parent.document !== document) _docs.push(window.parent.document) } catch (e) {}
    for (var _di = 0; _di < _docs.length; _di++) {
      (function (_d) {
        if (_d.__jvSfxBound) return
        _d.__jvSfxBound = true
        _d.addEventListener('pointerdown', function (e) {
          try { if (e.target && e.target.closest && e.target.closest('button,[role="button"]')) G.play('tap') } catch (x) {}
        }, true)
        _d.addEventListener('keydown', function (e) {
          try { if (e.target && e.target.closest && e.target.closest('input,textarea,[contenteditable="true"],[contenteditable=""]') && e.key && e.key.length === 1) G.play('typing') } catch (x) {}
        }, true)
      })(_docs[_di])
    }
  }
  document.body.classList.toggle('jarvis-thinking', !!(data && data.mode === 'thinking'))
  try { window.parent.document.body.classList.toggle('jarvis-thinking', !!(data && data.mode === 'thinking')) } catch (e) {}
  thinkSet(document.body.classList.contains('jarvis-thinking') || !!(data && data.mode === 'thinking'))
  if (data && data.token && G.lastToken !== data.token) {
    G.lastToken = data.token
    setTimeout(function () { G.play(data.event || 'boot') }, 120)
  }
}
"""

try:
    _MOBILE_SFX = _ccv2_component(
        "jarvis_mobile_sfx",
        '''<div style="display:none"></div>''',
        _MOBILE_SFX_JS,
    )
except Exception:
    _MOBILE_SFX = None


def _mobile_sfx(event: str = "", mode: str = "") -> None:
    if _MOBILE_SFX is None:
        return
    tok = ""
    if event:
        st.session_state["_sfx_seq"] = int(st.session_state.get("_sfx_seq", 0)) + 1
        tok = f"{event}:{st.session_state['_sfx_seq']}"
    try:
        _MOBILE_SFX(
            key="m_sfx_comp",
            data={
                "enabled": bool(st.session_state.get("m_sfx", True)),
                "volume": float(st.session_state.get("m_sfx_vol", 0.22)),
                "event": event,
                "token": tok,
                "mode": mode,
            },
            height=1,
        )
    except Exception:
        pass


def _mobile_boot() -> None:
    st.markdown(
        '<div class="mboot"><div class="mboot-grid"></div>'
        '<div class="mboot-core">◉</div>'
        '<div class="mboot-title">JARVIS OS</div>'
        '<div class="mboot-sub">Arc reactor online · initializing modules</div>'
        '<div class="mboot-bar"><i></i></div>'
        '<div class="mboot-sub">MIC · VISION · MEMORY · WEB</div></div>',
        unsafe_allow_html=True,
    )


_MOBILE_PWA_JS = r"""
export default function (component) {
  const { data, setTriggerValue } = component
  const G = window.__jarvisPWA || (window.__jarvisPWA = {})
  function push(page) {
    try {
      const params = new URLSearchParams(window.location.search)
      params.set('page', page)
      window.history.pushState({ jv: page }, '', '?' + params.toString())
    } catch (e) {}
  }
  if (!G.bound) {
    G.bound = true
    // Browser back → ask Python to open Home instead of leaving the app.
    window.addEventListener('popstate', function () {
      try { setTriggerValue('back', 'b' + Date.now()) } catch (e) {}
    })
  }
  const page = (data && data.page) || G.first || 'home'
  if (G.last !== page) {
    G.last = page
    try { push(page) } catch (e) {}
  }
  function inject(doc) {
    try {
      if (!doc) return
      if (!doc.querySelector('link[rel="manifest"]')) {
        const l = doc.createElement('link')
        l.rel = 'manifest'; l.href = '/static/manifest.json'
        doc.head.appendChild(l)
      }
      if (!doc.querySelector('meta[name="theme-color"]')) {
        const m = doc.createElement('meta')
        m.name = 'theme-color'; m.content = '#00d4ff'
        doc.head.appendChild(m)
      }
      if (!doc.querySelector('link[rel="apple-touch-icon"]')) {
        const a = doc.createElement('link')
        a.rel = 'apple-touch-icon'; a.href = '/static/icon-192.png'
        doc.head.appendChild(a)
      }
      if (!doc.querySelector('meta[name="mobile-web-app-capable"]')) {
        const c = doc.createElement('meta')
        c.name = 'mobile-web-app-capable'; c.content = 'yes'
        doc.head.appendChild(c)
      }
    } catch (e) {}
  }
  inject(document)
  try { inject(window.parent.document) } catch (e) {}
  try {
    if ('serviceWorker' in navigator && !window.__jarvisSW) {
      window.__jarvisSW = true
      navigator.serviceWorker.register('/static/sw.js').catch(function () {})
    }
  } catch (e) {}
}
"""

try:
    _MOBILE_PWA = _ccv2_component(
        "jarvis_mobile_pwa",
        '''<div style="display:none"></div>''',
        _MOBILE_PWA_JS,
    )
except Exception:
    _MOBILE_PWA = None


def _mobile_pwa_mount() -> None:
    if _MOBILE_PWA is None:
        return
    try:
        res = _MOBILE_PWA(
            key="m_pwa",
            data={"page": str(st.session_state.get("_mobile_page_sel") or "home")},
            height=1,
        )
    except Exception:
        return
    b = getattr(res, "back", None)
    if b and b != st.session_state.get("_back_ts"):
        st.session_state["_back_ts"] = b
        # Accept the URL page as "last seen" so the state override wins (deep links).
        _qp = _qp_str("page", "").strip().lower()
        if _qp in MOBILE_PAGES:
            st.session_state["_qp_last_page"] = _qp
        _mobile_nav("home")


# --- Real-time clock (browser timezone) + smooth auto-scroll for chat ---
_MOBILE_CLOCK_JS = r"""
export default function (component) {
  const W = window.parent
  // Global STOP coordination: any user interaction on parent stops TTS
  try {
    if (!W.__jarvisGlobalStopBound) {
      W.__jarvisGlobalStopBound = true
      function broadcastStop() {
        try {
          if (W.__jarvisTTS && W.__jarvisTTS.bc) W.__jarvisTTS.bc.postMessage('STOP')
        } catch (e) {}
      }
      W.document.addEventListener('click', function(e) {
        const t = e.target
        if (t && (t.tagName === 'BUTTON' || t.closest('button') || t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.closest('form'))) broadcastStop()
      }, true)
      W.document.addEventListener('submit', broadcastStop, true)
    }
  } catch (e) {}
  function pad(n) { return String(n).padStart(2, '0') }
  function tick() {
    try {
      const d = new Date()
      const doc = W.document
      let hh = d.getHours()
      const ap = hh >= 12 ? 'PM' : 'AM'
      let h12 = hh % 12; if (h12 === 0) h12 = 12
      const t12 = pad(h12) + ':' + pad(d.getMinutes()) + ' ' + ap
      const t24 = pad(hh) + ':' + pad(d.getMinutes())
      const dstr = d.toLocaleDateString(undefined, { weekday: 'short', day: '2-digit', month: 'short' })
      doc.querySelectorAll('.mj-time').forEach(function (e) { e.textContent = t24 })
      doc.querySelectorAll('.mj-time12').forEach(function (e) { e.textContent = t12 })
      doc.querySelectorAll('.mj-date').forEach(function (e) { e.textContent = dstr.toUpperCase() })
      const g = hh < 5 ? 'Night watch' : hh < 12 ? 'Good morning' : hh < 17 ? 'Good afternoon' : hh < 21 ? 'Good evening' : 'Good night'
      doc.querySelectorAll('.mj-greet').forEach(function (e) { e.textContent = g })
      const box = doc.querySelector('.st-key-m_chat_scroll')
      if (box) {
        let sc = box
        if (sc.scrollHeight <= sc.clientHeight + 4) {
          const inner = box.querySelector('[data-testid="stVerticalBlockBorderWrapper"], [data-testid="stVerticalBlock"]')
          if (inner && inner.scrollHeight > inner.clientHeight + 4) sc = inner
        }
        const n = doc.querySelectorAll('[data-testid="stChatMessage"]').length
        const prev = W.__jarvisChatCount || 0
        if (n !== prev) {
          W.__jarvisChatCount = n
          const near = sc.scrollHeight - sc.scrollTop - sc.clientHeight < 220
          if (n > prev || near) sc.scrollTop = sc.scrollHeight
        }
      }
    } catch (e) {}
  }
  try { if (W.__jarvisClockTimer) clearInterval(W.__jarvisClockTimer) } catch (e) {}
  try { W.__jarvisClockTimer = setInterval(tick, 1000); tick() } catch (e) {}
}
"""

try:
    _MOBILE_CLOCK = _ccv2_component(
        "jarvis_mobile_clock",
        '''<div style="display:none"></div>''',
        _MOBILE_CLOCK_JS,
    )
except Exception:
    _MOBILE_CLOCK = None


def _mobile_clock_mount() -> None:
    if _MOBILE_CLOCK is None:
        return
    try:
        _MOBILE_CLOCK(key="m_clock_comp", data={}, height=1)
    except Exception:
        pass


# --- Hold-to-talk mic (CCv2: Web Speech API on the phone, sends transcript to Python) ---
_MOBILE_HOLD_JS = r"""
export default function (component) {
  const { data, parentElement, setTriggerValue } = component
  const btn = parentElement.querySelector('#holdmic')
  const lbl = parentElement.querySelector('#holdlbl')
  const glow = parentElement.querySelector('#micglow')
  if (!btn) return
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition
  const G = window.__jarvisHold || (window.__jarvisHold = {})
  const supported = !!SR
  G.lang = (data && data.lang) || 'en-US'
  btn.style.opacity = supported ? '1' : '0.45'
  if (lbl) lbl.textContent = supported ? 'Hold to talk' : 'Type instead'
  let retries = 0
  function showGlow() {
    if (!glow || !btn) return
    const r = btn.getBoundingClientRect()
    glow.style.display = 'block'
    glow.style.left = (r.left + r.width / 2 - 110) + 'px'
    glow.style.top = (r.top + r.height / 2 - 110) + 'px'
  }
  function hideGlow() { if (glow) glow.style.display = 'none' }
  function setRec(on) {
    btn.classList.toggle('recording', on)
    try { document.body.classList.toggle('jarvis-listening', on) } catch (e) {}
    try { window.parent.document.body.classList.toggle('jarvis-listening', on) } catch (e) {}
    if (on) { if (lbl) lbl.textContent = 'Listening…' } else if (lbl) lbl.textContent = 'Hold to talk'
    if (glow) glow.style.display = on ? 'block' : 'none'
    if (window.__jarvisSFX) window.__jarvisSFX.play(on ? 'listen' : 'stop')
  }
  function begin(e) {
    e.preventDefault()
    // STOP any ongoing TTS the moment user starts speaking
    try { if (window.__jarvisTTS && window.__jarvisTTS.bc) window.__jarvisTTS.bc.postMessage('STOP') } catch (x) {}
    try { if (window.parent && window.parent.__jarvisTTS && window.parent.__jarvisTTS.bc) window.parent.__jarvisTTS.bc.postMessage('STOP') } catch (x) {}
    showGlow()                        // Red pulse shows IMMEDIATELY on press
    if (!supported) {
      if (lbl) lbl.textContent = 'Type instead'
      setTimeout(function () { if (!G.active) hideGlow() }, 1500)
      return
    }
    if (G.rec) { try { G.rec.abort() } catch (x) {} }
    G.text = ''
    retries = 0
    const rec = new SR()
    G.rec = rec
    rec.lang = G.lang
    rec.continuous = false
    rec.interimResults = true
    rec.maxAlternatives = 1
    rec.onstart = function () { G.active = true; setRec(true) }
    rec.onresult = function (ev) {
      let txt = ''
      for (let i = 0; i < ev.results.length; i++) txt += (ev.results[i][0] && ev.results[i][0].transcript) || ''
      G.text = txt.trim()
      if (lbl && G.text) lbl.textContent = '“' + G.text.slice(-34) + '”'
    }
    rec.onerror = function (err) {
      G.active = false
      setRec(false)
      if (lbl) {
        if (err.error === 'not-allowed' || err.error === 'service-not-allowed') lbl.textContent = 'Allow mic access'
        else if ((err.error === 'no-speech' || err.error === 'aborted') && retries < 2) {
          retries++
          lbl.textContent = 'Tap again'
          setTimeout(begin, 250)
        } else lbl.textContent = 'Try again — tap the mic'
      }
    }
    rec.onend = function () {
      G.active = false
      const t = (G.text || '').trim()
      if (t) { try { setTriggerValue('transcript', t) } catch (x) {} ; G.text = '' }
      setRec(false)
    }
    try { rec.start() } catch (x) {
      // Glow already shown; if SR never starts, clear it after a moment.
      setTimeout(function () { if (!G.active) { hideGlow(); if (lbl) lbl.textContent = 'Hold to talk' } }, 900)
    }
  }
  function end(e) {
    if (e) e.preventDefault()
    try { if (G.rec && G.active) G.rec.stop() } catch (x) {}
  }
  function bind() {
    if (!btn || btn.__jvHoldBound) return
    btn.__jvHoldBound = true
    btn.addEventListener('pointerdown', begin)
    btn.addEventListener('pointerup', end)
    btn.addEventListener('pointercancel', end)
    btn.addEventListener('pointerleave', end)
    btn.addEventListener('contextmenu', function (e) { e.preventDefault() })
  }
  bind()
  return function () {
    try { if (G.rec) G.rec.abort() } catch (e) {}
    try { window.parent.document.body.classList.remove('jarvis-listening') } catch (e) {}
    hideGlow()
  }
}
"""

try:
    _MOBILE_HOLD = _ccv2_component(
        "jarvis_mobile_hold",
        '''<div style="display:flex;flex-direction:column;align-items:center;gap:3px;background:transparent;">
  <button id="holdmic" type="button" title="Hold to talk" style="width:62px;height:62px;border-radius:50%;border:2px solid rgba(0,212,255,.55);background:radial-gradient(circle at 30% 25%, rgba(0,140,220,.55), rgba(0,24,48,.95));color:#bdf3ff;display:flex;align-items:center;justify-content:center;cursor:pointer;touch-action:none;-webkit-tap-highlight-color:transparent;box-shadow:0 0 18px rgba(0,212,255,.35), inset 0 0 14px rgba(0,212,255,.25);transition:transform .12s, box-shadow .12s, background .12s;outline:none;">
    <svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3z"/><path d="M19 10v2a7 7 0 0 1-14 0v-2"/><line x1="12" y1="19" x2="12" y2="22"/></svg>
  </button>
  <span id="holdlbl" style="font-size:9px;letter-spacing:.6px;color:#6f9ab8;white-space:nowrap;text-transform:uppercase;">Hold to talk</span>
  <!-- Pulse ring that expands around the mic while listening (light-transparent JARVIS red) -->
  <div id="micglow" style="display:none;position:fixed;width:220px;height:220px;border-radius:50%;pointer-events:none;z-index:6;background:radial-gradient(circle,rgba(255,85,119,.42) 0%,rgba(255,85,119,.16) 42%,rgba(255,85,119,.05) 68%,transparent 90%);box-shadow:0 0 30px rgba(255,85,119,.55),0 0 62px rgba(255,85,119,.3);animation:micglowpulse 1.1s ease-in-out infinite;"></div>
  <style>
    #holdmic.recording { background: radial-gradient(circle at 30% 25%, #ff5577, #b3002b) !important; border-color:#ff3355 !important; color:#fff !important; box-shadow:0 0 34px rgba(255,51,85,.85), inset 0 0 18px rgba(255,51,85,.5) !important; animation: holdpulse .6s ease-in-out infinite; }
    @keyframes holdpulse { 0%,100% { transform:scale(1); } 50% { transform:scale(1.07); } }
    @keyframes micglowpulse { 0%,100% { opacity:.85; transform: translate(-50%,-50%) scale(.85); } 50% { opacity:1; transform: translate(-50%,-50%) scale(1.22); } }
  </style>
</div>''',
        _MOBILE_HOLD_JS,
    )
except Exception:
    _MOBILE_HOLD = None


def _mobile_hold_mount() -> None:
    if _MOBILE_HOLD is None:
        return
    try:
        res = _MOBILE_HOLD(
            key="m_hold",
            data={"lang": st.session_state.get("stt_lang", "en-US")},
            on_transcript_change=lambda: None,
            height=88,
        )
    except Exception:
        return
    t = getattr(res, "transcript", None)
    if isinstance(t, str) and t.strip():
        t = t.strip()
        import hashlib as _hl
        h = _hl.md5(t.encode()).hexdigest()
        if h != st.session_state.get("_m_hold_hash"):
            st.session_state["_m_hold_hash"] = h
            _mobile_send(t, source="voice")


def _mobile_nav(page: str, sfx: str = "") -> None:
    """Instant client-side page switch: state only, no URL change, no extra rerun."""
    st.session_state["_mobile_page_sel"] = page
    st.session_state["_nav_ts"] = time.time()
    if sfx:
        st.session_state["_sfx_after"] = sfx


def _reactor_html() -> str:
    import datetime as _d
    now = _d.datetime.now()
    hr = now.hour
    if hr < 5:
        greet = "Night watch"
    elif hr < 12:
        greet = "Good morning"
    elif hr < 17:
        greet = "Good afternoon"
    elif hr < 21:
        greet = "Good evening"
    else:
        greet = "Good night"
    return f"""
<div class="mreactor-wrap">
  <div class="mreactor">
    <div class="ticks"></div>
    <div class="mring r1"></div>
    <div class="mring r2"></div>
    <div class="mring r3"></div>
    <div class="mring r4"></div>
    <div class="mglow"></div>
    <div class="mcoil"></div>
    <div class="mcore-inner">
      <div class="mtime mj-time">{now.strftime('%H:%M')}</div>
      <div class="mdate mj-date">{now.strftime('%a %d %b').upper()}</div>
      <div class="mgreet mj-greet">{greet}</div>
    </div>
  </div>
</div>
"""


def _mobile_led_row() -> str:
    tasks = st.session_state.get("tasks") or load_tasks()
    open_tasks = sum(1 for t in tasks if not t.get("done"))
    facts = 0
    try:
        facts = mem.memory_stats()["memories"] if mem else 0
    except Exception:
        facts = 0
    mic = "HF" if st.session_state.get("_hf_enabled") else "TAP"
    model = LABELS.get(st.session_state.get("model_sel", DEFAULT), DEFAULT).split(" (")[0]
    model = model.replace("Nemotron 3.5 Super VL", "Nemotron").replace("Gemma 4 31B IT", "Gemma 4")
    return (
        '<div class="mleds">'
        f'<span class="mled">MIC <b>{mic}</b></span>'
        f'<span class="mled">MEM <b>{facts}</b></span>'
        f'<span class="mled">TASKS <b>{open_tasks}</b></span>'
        f'<span class="mled">MODEL <b>{model[:14]}</b></span>'
        f'<span class="mled">NET <b>LIVE</b></span>'
        '</div>'
    )


def _mobile_header() -> None:
    import datetime as _d
    now = _d.datetime.now()
    if st.session_state.get("_mobile_gen"):
        txt, cls = "⚡ THINKING", "mchip think"
    elif st.session_state.get("_hf_enabled"):
        txt, cls = "🎙 LISTENING", "mchip listen"
    else:
        txt, cls = "● ONLINE", "mchip"
    st.markdown(
        f'<div class="mhdr"><div class="mhdr-left"><div><div class="mlogo"><i>◉</i> JARVIS</div>'
        f'<div class="msub">MARK VII · OS</div></div></div>'
        f'<div style="text-align:right;"><div class="mclock"><span class="mj-time12">{now.strftime("%I:%M %p")}</span></div>'
        f'<div class="msub mj-date">{now.strftime("%a %d %b").upper()}</div>'
        f'<div class="{cls}" style="margin-top:3px;">{txt}</div></div></div>',
        unsafe_allow_html=True,
    )


def _mobile_top(title: str, back_key: str = "") -> None:
    if st.button("← Dashboard", key=f"mback_{back_key or title}", on_click=_mobile_nav, args=("home",)):
        pass
    st.markdown(f'<div class="mtitle">{title}</div>', unsafe_allow_html=True)


def _mobile_key_gate() -> None:
    st.markdown('<div class="mhdr"><div class="mlogo">◉ JARVIS</div><div class="mchip">● SETUP</div></div>', unsafe_allow_html=True)
    st.markdown("### Connect OpenRouter")
    st.caption("Add your key once. It is saved locally in the JARVIS .env on the host machine.")
    k = st.text_input("OpenRouter API key", type="password", placeholder="sk-or-v1-...")
    if st.button("Unlock JARVIS", type="primary", width="stretch"):
        if valid_key(k):
            global _JARVIS_API_KEY
            _JARVIS_API_KEY = k.strip()
            persist_key(k.strip())
            st.rerun()
        else:
            st.error("Invalid key — it must start with sk-or-v1-")


def _mobile_clean_content(text: str) -> str:
    t = text or ""
    t = re.sub(r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F-\x9F]", " ", t)
    t = re.sub(r"\[(VIDEO|MUSIC):\s*https?://[^\]]+\]", "", t).strip()
    return t or "🎵 Playing in Media →"


def _mobile_send(text: str, source: str = "chat") -> None:
    text = (text or "").strip()
    if not text:
        return
    st.session_state.setdefault("msgs", []).append({"role": "user", "content": text})
    st.session_state["_last_sources"] = []
    try:
        if mem:
            mem.log_turn("user", text, source, st.session_state.get("_mobile_page", ""), st.session_state.get("model_sel", ""))
            try:
                mem.apply_correction_local(text)
            except Exception:
                pass
            if source == "camera":
                st.session_state["_cam_prompt_ts"] = time.time()
    except Exception:
        pass
    st.session_state["_mobile_gen"] = True
    st.session_state["_mobile_gen_ts"] = time.time()
    st.session_state["_sfx_after"] = "send"
    st.rerun()


def _mobile_mcard(col, icon: str, title: str, subtitle: str, page: str, key: str) -> None:
    with col:
        with st.container(key=f"mtile_{key}"):
            st.markdown(
                f'<div class="mtile-corner">›</div>'
                f'<div class="mtile-icon">{icon}</div>'
                f'<div class="mtile-title">{title}</div>'
                f'<div class="mtile-sub">{subtitle}</div>',
                unsafe_allow_html=True,
            )
            st.button(
                f"Open {title}", key=f"mnav_{key}", width="stretch",
                on_click=_mobile_nav, args=(page,),
            )


_MOBILE_TILES_HTML = '''<div id="tilegrid" class="m_home_grid" style="visibility:hidden;">
  <button class="mtile" id="tile_chat" type="button"><span class="mtile-icon">💬</span><span class="mtile-title">CHAT · VOICE</span><span id="sub_chat" class="mtile-sub">Hold mic or type</span></button>
  <button class="mtile" id="tile_camera" type="button"><span class="mtile-icon">📷</span><span class="mtile-title">CAMERA</span><span class="mtile-sub">Scan · OCR · vision</span></button>
  <button class="mtile" id="tile_media" type="button"><span class="mtile-icon">🎵</span><span class="mtile-title">MEDIA</span><span id="sub_media" class="mtile-sub">Song</span></button>
  <button class="mtile" id="tile_tasks" type="button"><span class="mtile-icon">📋</span><span class="mtile-title">TASKS</span><span id="sub_tasks" class="mtile-sub">2 open</span></button>
  <button class="mtile" id="tile_weather" type="button"><span class="mtile-icon">🌤</span><span class="mtile-title">WEATHER</span><span id="sub_weather" class="mtile-sub">24°C · Bengaluru</span></button>
  <button class="mtile" id="tile_system" type="button"><span class="mtile-icon">🖥</span><span class="mtile-title">SYSTEM</span><span class="mtile-sub">Host CPU · RAM · disk</span></button>
  <button class="mtile" id="tile_models" type="button"><span class="mtile-icon">🧠</span><span class="mtile-title">MODELS</span><span id="sub_models" class="mtile-sub">Gemma 4</span></button>
  <button class="mtile" id="tile_memory" type="button"><span class="mtile-icon">🗂</span><span class="mtile-title">MEMORY</span><span id="sub_memory" class="mtile-sub">12 facts learned</span></button>
  <button class="mtile" id="tile_settings" type="button"><span class="mtile-icon">⚙</span><span class="mtile-title">SETTINGS</span><span class="mtile-sub">Voice · sounds · key</span></button>
  <button class="mtile" id="tile_voice" type="button"><span class="mtile-icon">🎙</span><span class="mtile-title">TAP-TO-TALK</span><span class="mtile-sub">Fallback voice page</span></button>
</div>
<style>
  #tilegrid { display: grid; grid-template-columns: 1fr 1fr; gap: 9px; padding: 6px 4px 4px; margin-top: 6px; }
  .mtile { display:flex; flex-direction:column; align-items:center; gap:6px; background:transparent; border:none; color:#e8f7ff; cursor:pointer; text-align:center; touch-action:manipulation; -webkit-tap-highlight-color:transparent; border-radius:14px; }
  .mtile:active { background: rgba(0,212,255,.07); }
  .mtile-icon { font-size:23px; }
  .mtile-title { font-size:12px; font-family:Orbitron,monospace; font-weight:800; letter-spacing:1.2px; color:#e8f7ff; text-transform:uppercase; margin:0; }
  .mtile-sub { font-size:9px; color:#7fa8c4; text-transform:none; letter-spacing:0; }
</style>'''

_MOBILE_TILES_JS = r"""
export default function (component) {
  const { data, parentElement, setTriggerValue } = component
  const grid = parentElement.querySelector('#tilegrid')
  if (!grid) return
  const page = (data && data.page) || 'home'
  grid.style.visibility = (page !== 'home') ? 'hidden' : ''
  const setSub = (id, txt) => { const el = grid.querySelector('#sub_' + id); if (el && txt) el.textContent = txt }
  if (data && data.media) setSub('media', data.media)
  if (data && data.tasks) setSub('tasks', data.tasks)
  if (data && data.weather) setSub('weather', data.weather)
  if (data && data.models) setSub('models', data.models)
  if (data && data.memory) setSub('memory', data.memory)
  for (const b of grid.querySelectorAll('.mtile')) {
    b.addEventListener('click', () => { 
      try { if (window.__jarvisSFX) window.__jarvisSFX.play('nav') } catch (e) {}
      try { if (window.__jarvisTTS && window.__jarvisTTS.bc) window.__jarvisTTS.bc.postMessage('STOP') } catch (e) {}
      try { if (window.parent && window.parent.__jarvisTTS && window.parent.__jarvisTTS.bc) window.parent.__jarvisTTS.bc.postMessage('STOP') } catch (e) {}
      setTriggerValue('nav', b.id.slice('tile_'.length)) 
    })
  }
}
"""

try:
    _MOBILE_TILES = _ccv2_component("jarvis_mobile_tiles", _MOBILE_TILES_HTML, _MOBILE_TILES_JS)
except Exception:
    _MOBILE_TILES = None


def _mobile_tiles_mount() -> None:
    """Mount the native tiles grid. Clicking a tile fires a trigger -> page switch."""
    if _MOBILE_TILES is None:
        return
    try:
        now_playing = str(st.session_state.get("music_title") or "—")[:24]
        tasks = st.session_state.get("tasks") or load_tasks()
        open_tasks = sum(1 for t in tasks if not t.get("done"))
        w = get_weather_cached()
        facts = 0
        try:
            facts = mem.memory_stats()["memories"] if mem else 0
        except Exception:
            facts = 0
        res = _MOBILE_TILES(
            key="m_tiles",
            data={
                "page": str(st.session_state.get("_mobile_page_sel") or "home"),
                "media": now_playing,
                "tasks": f"{open_tasks} open",
                "weather": f'{w["temp"]:.0f}°C · Bengaluru',
                "models": LABELS.get(st.session_state.get("model_sel", DEFAULT), "")[:24],
                "memory": f"{facts} facts learned",
            },
            height=262,
        )
        nav = getattr(res, "nav", None)
    except Exception:
        return
    if isinstance(nav, str) and nav in MOBILE_PAGES and nav != st.session_state.get("_tiles_nav"):
        st.session_state["_tiles_nav"] = nav
        st.session_state["_mobile_page_sel"] = nav
        st.rerun()


def _mobile_page_home() -> None:
    w = get_weather_cached()
    tasks = st.session_state.get("tasks") or load_tasks()
    open_tasks = sum(1 for t in tasks if not t.get("done"))
    now_playing = str(st.session_state.get("music_title") or "—")[:24]
    mic_state = "Listening" if st.session_state.get("_hf_enabled") else ("Thinking" if st.session_state.get("_mobile_gen") else "Tap to talk")
    facts = 0
    try:
        facts = mem.memory_stats()["memories"] if mem else 0
    except Exception:
        facts = 0
    st.markdown(_reactor_html(), unsafe_allow_html=True)
    st.markdown(_mobile_led_row(), unsafe_allow_html=True)
    if _MOBILE_TILES is not None:
        _mobile_tiles_mount()
    else:
        with st.container(key="m_home_grid"):
            c1, c2 = st.columns(2)
            _mobile_mcard(c1, "💬", "Chat · Voice", "Hold mic or type", "chat", "chat")
            _mobile_mcard(c2, "📷", "Camera", "Scan · OCR · vision", "camera", "camera")
            c1, c2 = st.columns(2)
            _mobile_mcard(c1, "🎵", "Media", now_playing, "media", "media")
            _mobile_mcard(c2, "📋", "Tasks", f"{open_tasks} open", "tasks", "tasks")
            c1, c2 = st.columns(2)
            _mobile_mcard(c1, "🌤", "Weather", f'{w["temp"]:.0f}°C · Bengaluru', "weather", "weather")
            _mobile_mcard(c2, "🖥", "System", "Host CPU · RAM · disk", "system", "system")
            c1, c2 = st.columns(2)
            _mobile_mcard(c1, "🧠", "Models", LABELS.get(st.session_state.get("model_sel", DEFAULT), "")[:24], "models", "models")
            _mobile_mcard(c2, "🗂", "Memory", f"{facts} facts learned", "memory", "memory")
            c1, c2 = st.columns(2)
            _mobile_mcard(c1, "⚙", "Settings", "Voice · sounds · key", "settings", "settings")
            _mobile_mcard(c2, "🎙", "Tap-to-talk", "Fallback voice page", "voice", "voice")
    if st.session_state.get("msgs"):
        last = next((m.get("content", "") for m in reversed(st.session_state["msgs"]) if m.get("role") == "assistant"), "")
        if last:
            st.markdown(f'<div class="mnote" style="margin-top:8px;">Last: {last[:120]}</div>', unsafe_allow_html=True)
    st.markdown('<div class="mnote" style="text-align:center;margin-top:10px;">MIC · CAMERA · SPEAKER RUN ON YOUR PHONE · ANSWERS ARE WEB-GROUNDED</div>', unsafe_allow_html=True)


def _mobile_page_chat(api_key, model, use_fast, use_voice) -> None:
    st.markdown('<style id="m-chat-flag"></style>', unsafe_allow_html=True)
    with st.container(key="m_chat_head"):
        h1, h2 = st.columns([1, 5], vertical_alignment="center")
        with h1:
            st.button("←", key="mchat_back", on_click=_mobile_nav, args=("home", "back"), help="Back to dashboard")
        with h2:
            st.markdown('<div class="mtitle">CHAT · VOICE</div>', unsafe_allow_html=True)

    msgs = st.session_state.get("msgs", [])
    with st.container(key="m_chat_scroll", border=False):
        if not msgs:
            st.markdown(
                '<div class="hud"><div class="ht">JARVIS</div>'
                '<div style="font-size:13px;color:#b9d7ea;">Hold the mic and speak — release to send. Or type below. Answers are web-grounded and spoken on your phone.</div></div>',
                unsafe_allow_html=True,
            )
            chips = ["What's the weather?", "Tech news today", "Play lo-fi beats", "System status"]
            cc = st.columns(2)
            for i, chip in enumerate(chips):
                with cc[i % 2]:
                    if st.button(chip, key=f"mchat_chip_{i}", width="stretch"):
                        _mobile_send(chip)
        for m in msgs[-40:]:
            with st.chat_message(m.get("role", "assistant")):
                st.markdown(_mobile_clean_content(m.get("content", "")))
        if st.session_state.get("_mobile_gen"):
            with st.chat_message("assistant"):
                st.markdown("⚡ **JARVIS is thinking…**")
        srcs = st.session_state.get("_last_sources") or []
        if srcs and msgs and msgs[-1].get("role") == "assistant":
            with st.expander(f"Sources ({len(srcs)})"):
                for s in srcs[:6]:
                    title = s.get("title") or s.get("url", "")
                    url = s.get("url", "")
                    st.markdown(f"- [{title}]({url})" if url else f"- {title}")

    if use_voice and msgs and not st.session_state.get("_mobile_gen"):
        last_a = next((m for m in reversed(msgs) if m.get("role") == "assistant"), None)
        if last_a:
            _mobile_tts(last_a.get("content", ""), last_a.get("_tts_id", ""))

    with st.container(key="m_chat_bar"):
        c1, c2 = st.columns([5.4, 1.5], vertical_alignment="center")
        with c1:
            with st.form("m_chat_form", clear_on_submit=True, border=False):
                f1, f2 = st.columns([5, 1], vertical_alignment="center")
                with f1:
                    prompt = st.text_input("Message", placeholder="Ask JARVIS…", label_visibility="collapsed")
                with f2:
                    sent = st.form_submit_button("➤", width="stretch")
                if sent and (prompt or "").strip():
                    _mobile_send(prompt.strip())
        with c2:
            _mobile_hold_mount()

    if st.session_state.get("_m_last_heard"):
        st.caption(f'Heard: “{st.session_state["_m_last_heard"]}”')


def _mobile_transcribe(wav_bytes: bytes, lang: str = "en-US") -> str:
    try:
        import io as _io
        import concurrent.futures as _cf
        rec = sr.Recognizer()
        with sr.AudioFile(_io.BytesIO(wav_bytes)) as src:
            audio = rec.record(src)
        ex = _cf.ThreadPoolExecutor(max_workers=1)
        fut = ex.submit(rec.recognize_google, audio, language=lang)
        try:
            return (fut.result(timeout=18) or "").strip()
        except Exception:
            return ""
        finally:
            ex.shutdown(wait=False, cancel_futures=True)
    except sr.UnknownValueError:
        return ""
    except Exception:
        return ""


def _mobile_hf_mount() -> None:
    if _MOBILE_HF is None:
        return
    try:
        res = _MOBILE_HF(
            key="m_hf",
            data={
                "enabled": bool(st.session_state.get("_hf_enabled")),
                "wake": "jarvis",
                "requireWake": True,
                "lang": st.session_state.get("stt_lang", "en-US"),
            },
            on_heard_change=lambda: None,
            height=48,
        )
    except Exception:
        return
    heard = getattr(res, "heard", None)
    if isinstance(heard, str) and heard.strip():
        h = heard.strip()
        hk = h.lower()
        now = time.time()
        # Ignore self-echo: while thinking, right after a spoken reply, or an exact repeat.
        if st.session_state.get("_mobile_gen"):
            return
        if (now - float(st.session_state.get("_last_tts_ts") or 0)) < 2.5:
            return
        prev = st.session_state.get("_m_heard_last") or ("", 0.0)
        try:
            prev_txt, prev_ts = str(prev[0]), float(prev[1])
        except Exception:
            prev_txt, prev_ts = "", 0.0
        if hk == prev_txt and (now - prev_ts) < 7:
            return
        st.session_state["_m_heard_last"] = (hk, now)
        st.session_state["_m_last_heard"] = h
        _mobile_send(h, source="voice")


def _mobile_page_voice(use_voice) -> None:
    _mobile_top("Voice", "voice")
    hf_prev = bool(st.session_state.get("_hf_enabled", False))
    hf_now = st.toggle("Hands-free — say “Jarvis …”", value=hf_prev, key="m_hf_toggle")
    if hf_now != hf_prev:
        st.session_state["_hf_enabled"] = hf_now
    st.caption("Hands-free works best in Chrome on Android. Tap-to-talk works on every phone.")
    _mobile_hf_mount()
    st.markdown('<div class="mnote">Tap the mic, speak, then stop — JARVIS transcribes and answers. The phone mic and speaker do the work.</div>', unsafe_allow_html=True)
    audio = st.audio_input("Tap to record", sample_rate=16000, key="m_audio")
    if audio is not None:
        try:
            raw = audio.getvalue()
        except Exception:
            raw = b""
        import hashlib as _hl
        h = _hl.md5(raw).hexdigest() if raw else ""
        if h and h != st.session_state.get("_m_audio_hash"):
            st.session_state["_m_audio_hash"] = h
            with st.spinner("Transcribing…"):
                text = _mobile_transcribe(raw, st.session_state.get("stt_lang", "en-US"))
            if text:
                st.session_state["_m_last_heard"] = text
                try:
                    if mem and raw:
                        mem.save_voice_clip(raw, text)
                except Exception:
                    pass
                _mobile_send(text, source="voice")
            else:
                st.warning("I couldn't understand that — please try again, a little closer to the mic.")
    if st.session_state.get("_m_last_heard"):
        st.caption(f'Heard: “{st.session_state["_m_last_heard"]}”')
    msgs = st.session_state.get("msgs", [])
    for m in msgs[-4:]:
        with st.chat_message(m.get("role", "assistant")):
            st.markdown(_mobile_clean_content(m.get("content", "")))
    if st.session_state.get("_mobile_gen"):
        with st.chat_message("assistant"):
            st.markdown("⚡ **JARVIS is thinking…**")
    if use_voice and msgs and not st.session_state.get("_mobile_gen"):
        last_a = next((m for m in reversed(msgs) if m.get("role") == "assistant"), None)
        if last_a:
            _mobile_tts(last_a.get("content", ""), last_a.get("_tts_id", ""))


def _mobile_page_camera() -> None:
    _mobile_top("Camera", "camera")
    st.caption("Uses your phone camera. Allow access when your browser asks.")
    cam = st.camera_input("Camera", key="m_cam", label_visibility="collapsed")
    if cam is not None:
        try:
            raw_cam = cam.getvalue()
            st.session_state.camera_bytes = raw_cam
            if mem:
                import hashlib as _hl
                h = _hl.md5(raw_cam).hexdigest()
                if h != st.session_state.get("_m_cam_hash"):
                    st.session_state["_m_cam_hash"] = h
                    mem.save_snapshot(raw_cam)
        except Exception:
            pass
    c1, c2 = st.columns(2)
    with c1:
        if st.button("🔍 Analyze", key="m_cam_analyze", type="primary", width="stretch"):
            if st.session_state.get("camera_bytes"):
                _mobile_send("Scan this image and describe what you see", source="camera")
            else:
                st.warning("Take a photo first.")
    with c2:
        if st.button("🗑 Clear", key="m_cam_clear", width="stretch"):
            st.session_state.camera_bytes = None
            st.rerun()
    if st.session_state.get("camera_bytes"):
        st.caption("📸 Photo ready — tap Analyze.")
    last_a = next((m for m in reversed(st.session_state.get("msgs", [])) if m.get("role") == "assistant"), None)
    if last_a:
        with st.chat_message("assistant"):
            st.markdown(_mobile_clean_content(last_a.get("content", "")))


def _mobile_spotify_meta(url: str) -> dict:
    cache = st.session_state.get("meta_cache") or {}
    if url in cache:
        t, a, th = cache[url]
        return {"title": t, "artist": a, "thumb": th}
    try:
        o = requests.get("https://open.spotify.com/oembed", params={"url": url}, timeout=4)
        if o.status_code == 200:
            j = o.json()
            meta = {"title": j.get("title", ""), "artist": j.get("author_name", ""), "thumb": j.get("thumbnail_url", "")}
            cache[url] = (meta["title"], meta["artist"], meta["thumb"])
            st.session_state["meta_cache"] = cache
            return meta
    except Exception:
        pass
    return {"title": st.session_state.get("music_title", ""), "artist": "", "thumb": ""}


def _mobile_page_media() -> None:
    _mobile_top("Media", "media")
    st.markdown("#### ▶ YouTube")
    q = st.text_input("Search YouTube", placeholder="Tech news today…", key="m_yt_q")
    if st.button("Search & play", key="m_yt_search", width="stretch") and q.strip():
        with st.spinner("Finding video…"):
            url = search_youtube(q.strip())
        if url:
            st.session_state.video_url = url
            st.session_state.video_title = q.strip()
        else:
            st.warning("No video found — try another search.")
    vurl = st.session_state.get("video_url") or ""
    if vurl:
        try:
            st.video(vurl, width="stretch", alt="YouTube video")
        except Exception:
            st.video(vurl)
        if st.session_state.get("video_title"):
            st.caption(st.session_state["video_title"])
    else:
        st.info("No video yet — search above or ask for today's tech news.")

    st.markdown("#### ♫ Music")
    murl = st.session_state.get("music_url") or ""
    if murl:
        idm = re.search(r"/track/([A-Za-z0-9]{22})", murl)
        if idm:
            meta = _mobile_spotify_meta(murl)
            if meta.get("thumb"):
                st.image(meta["thumb"], width=140, alt="Album art")
            st.markdown(f'**{meta.get("title") or st.session_state.get("music_title") or "Song"}**')
            if meta.get("artist"):
                st.caption(meta["artist"])
            try:
                st.iframe(f"https://open.spotify.com/embed/track/{idm.group(1)}?theme=0", height=152, alt="Spotify player")
            except Exception:
                pass
            st.link_button("Open in Spotify", murl, width="stretch")
        else:
            # Full-song YouTube playback (most reliable on phones, no login needed)
            title = st.session_state.get("music_title") or "Song"
            query = st.session_state.get("music_query") or title
            meta = itunes_song_meta(query)
            c1, c2 = st.columns([1, 2])
            with c1:
                if meta.get("art"):
                    st.image(meta["art"], width=120, alt="Album art")
            with c2:
                st.markdown(f'**{meta.get("title") or title}**')
                if meta.get("artist"):
                    st.caption(meta["artist"])
            if meta.get("preview"):
                st.caption("30-second preview")
                st.audio(meta["preview"], autoplay=True)
            try:
                st.video(murl, width="stretch", alt="Song video")
            except Exception:
                st.link_button("Open song", murl, width="stretch")
            st.link_button("Open in Spotify", f"https://open.spotify.com/search/{requests.utils.quote(query)}", width="stretch")
    else:
        st.info("No song yet — say “play <song>” in Chat or Voice.")


def _mobile_page_tasks() -> None:
    _mobile_top("Tasks", "tasks")
    if "tasks" not in st.session_state:
        st.session_state.tasks = load_tasks()
    tasks = st.session_state.tasks
    if not tasks:
        st.info("No tasks yet — add one below.")
    for i, t in enumerate(list(tasks)):
        c1, c2, c3 = st.columns([5, 1, 1])
        with c1:
            done = st.checkbox(t.get("title", "Task"), value=bool(t.get("done")), key=f"mtask_{i}")
            if done != bool(t.get("done")):
                tasks[i]["done"] = done
                save_tasks(tasks)
                st.rerun()
        with c2:
            st.caption(t.get("time", ""))
        with c3:
            if st.button("🗑", key=f"mtask_del_{i}"):
                tasks.pop(i)
                save_tasks(tasks)
                st.rerun()
    new = st.text_input("New task", placeholder="Add a task…", key="m_new_task")
    c1, c2 = st.columns(2)
    with c1:
        if st.button("＋ Add", key="m_add_task", width="stretch"):
            if new.strip():
                tasks.append({"title": new.strip(), "time": "Today", "done": False})
                save_tasks(tasks)
                st.rerun()
    with c2:
        if st.button("Clear done", key="m_clear_done", width="stretch"):
            st.session_state.tasks = [t for t in tasks if not t.get("done")]
            save_tasks(st.session_state.tasks)
            st.rerun()


def _mobile_page_weather() -> None:
    _mobile_top("Weather", "weather")
    w = get_weather_cached()
    st.markdown(f'<div class="mbig">{w["temp"]:.1f}°C</div>', unsafe_allow_html=True)
    st.markdown(f'<div class="mnote">Bengaluru · High {w["max"]:.0f}° · Low {w["min"]:.0f}°</div>', unsafe_allow_html=True)
    c1, c2 = st.columns(2)
    c1.metric("Humidity", f'{w["hum"]}%')
    c2.metric("Wind", f'{w["wind"]} km/h')
    if st.button("↻ Refresh", key="m_weather_refresh", width="stretch"):
        get_weather_cached.clear()
        st.rerun()


def _mobile_page_system() -> None:
    _mobile_top("System", "system")
    st.caption("JARVIS host (PC) — not your phone.")
    try:
        import psutil as _ps
        cpu = float(_ps.cpu_percent(interval=0.2))
        mem = float(_ps.virtual_memory().percent)
    except Exception:
        cpu, mem = 0.0, 0.0
    st.metric("CPU", f"{cpu:.0f}%")
    st.progress(min(1.0, max(0.0, cpu / 100.0)))
    st.metric("RAM", f"{mem:.0f}%")
    st.progress(min(1.0, max(0.0, mem / 100.0)))
    try:
        import shutil as _sh
        du = _sh.disk_usage("C:\\" if os.name == "nt" else "/")
        dp = du.used / du.total * 100
        st.metric("Disk", f"{dp:.0f}%")
        st.progress(min(1.0, max(0.0, dp / 100.0)))
        st.caption(f"{du.used // (1024**3)} GB used of {du.total // (1024**3)} GB")
    except Exception:
        pass
    try:
        import subprocess as _sp
        r = _sp.run(["nvidia-smi", "--query-gpu=utilization.gpu", "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=3)
        if r.stdout.strip():
            st.metric("GPU", f"{int(float(r.stdout.strip().split()[0]))}%")
    except Exception:
        pass


def _mobile_page_models() -> None:
    _mobile_top("AI models", "models")
    with st.container(border=True, key="m_models_box"):
        st.markdown('<div class="ht">AI MODELS — USED</div>', unsafe_allow_html=True)
        current = st.session_state.get("model_sel", DEFAULT)
        for mid in MODELS:
            active = mid == current
            label = ("● " if active else "○ ") + LABELS.get(mid, mid) + (" — ACTIVE" if active else " — FREE")
            if st.button(label, key=f"mmodel_{mid[:14]}", width="stretch", type="primary" if active else "secondary"):
                st.session_state.model_sel = mid
                st.rerun()
        st.caption(f"Active: {LABELS.get(current, current)}")


def _mobile_page_memory() -> None:
    _mobile_top("Memory", "memory")
    if mem is None:
        st.warning("Memory engine is not available.")
        return
    stats = mem.memory_stats()
    st.markdown(
        f'<div class="mbig" style="font-size:34px;">{stats["memories"]}</div>'
        f'<div class="mnote">{stats["turns"]} turns · {stats["voice"]} voice clips · '
        f'{stats["snapshots"]} snapshots · {stats["media_mb"]} MB</div>',
        unsafe_allow_html=True,
    )
    t1, t2, t3, t4 = st.tabs(["Facts", "Voice", "Snapshots", "Summaries"])

    with t1:
        newm = st.text_input("Add a memory", placeholder="e.g. I am learning Python", key="m_mem_add_txt")
        if st.button("＋ Remember this", key="m_mem_add_btn", width="stretch") and newm.strip():
            mem.add_memory(newm.strip(), "fact", 4)
            st.rerun()
        facts = mem.list_memories(limit=200)
        if not facts:
            st.caption("Nothing learned yet. Talk normally — I store and update facts automatically.")
        else:
            # Show the memory sections (identity / preference / goal / …)
            secs: dict = {}
            for f in facts:
                k = f.get("kind", "fact") or "fact"
                secs[k] = secs.get(k, 0) + 1
            st.markdown('<div class="mnote">' + " · ".join(f"{k}: {v}" for k, v in sorted(secs.items())) + "</div>", unsafe_allow_html=True)
        for f in facts[:80]:
            c1, c2 = st.columns([5, 1])
            with c1:
                st.markdown(f'<div class="mrow"><span>{f.get("text", "")[:220]}</span></div>', unsafe_allow_html=True)
            with c2:
                if st.button("✕", key=f"mdel_{f['id']}", help="Forget"):
                    mem.delete_memory(int(f["id"]))
                    st.rerun()
        if len(facts) > 80:
            st.caption(f"Showing 80 of {len(facts)} — the memory store is large and grows automatically.")
        if facts and st.button("Clear all facts", key="m_mem_clear_facts", width="stretch"):
            mem.clear_memories()
            st.rerun()

    with t2:
        clips = mem.list_media("voice", 24)
        if not clips:
            st.caption("No voice clips yet — tap-to-talk audio is saved here.")
        for v in clips:
            try:
                st.caption(f"{time.strftime('%d %b %H:%M', time.localtime(v['created']))} · {v.get('description','')[:160]}")
                st.audio(v["path"])
                if st.button("✕ Delete clip", key=f"mvdel_{v['id']}"):
                    mem.delete_media(int(v["id"]))
                    st.rerun()
            except Exception:
                continue

    with t3:
        shots = mem.list_media("snapshot", 18)
        if not shots:
            st.caption("No camera snapshots yet.")
        for s in shots:
            try:
                st.image(s["path"], width=220, caption=(s.get("description") or "Snapshot")[:220])
                if st.button("✕ Delete snapshot", key=f"msdel_{s['id']}"):
                    mem.delete_media(int(s["id"]))
                    st.rerun()
            except Exception:
                continue

    with t4:
        sums = mem.latest_summaries(6)
        if not sums:
            st.caption("A daily summary appears after your first full day of conversations.")
        for s in sums:
            st.markdown(f'<div class="mrow"><b>{s.get("day","")}</b><br>{s.get("text","")}</div>', unsafe_allow_html=True)

    st.markdown("#### Danger zone")
    confirm = st.checkbox("I understand this erases everything", key="m_mem_wipe_ok")
    if st.button("Erase all memory + media", key="m_mem_wipe", width="stretch", disabled=not confirm):
        mem.wipe_all()
        save_user_profile(dict(DEFAULT_USER_PROFILE))
        st.success("Memory wiped.")
        st.rerun()


def _mobile_page_settings(api_key: str) -> None:
    global _JARVIS_API_KEY
    _mobile_top("Settings", "settings")
    st.markdown("#### OpenRouter key")
    nk = st.text_input("API key", type="password", placeholder="sk-or-v1-...", key="m_key_input")
    c1, c2 = st.columns(2)
    with c1:
        if st.button("Save", key="m_key_save", width="stretch"):
            if valid_key(nk):
                _JARVIS_API_KEY = nk.strip()
                persist_key(nk.strip())
                st.success("Saved")
                st.rerun()
            else:
                st.error("Invalid key")
    with c2:
        if st.button("Clear", key="m_key_clear", width="stretch"):
            _JARVIS_API_KEY = ""
            persist_key("")
            st.rerun()
    st.caption(f"Active: {api_key[:8]}…{api_key[-4:]}")
    st.markdown("#### Model")
    cur = st.session_state.get("model_sel", DEFAULT)
    pick = st.selectbox("Model", MODELS, index=MODELS.index(cur) if cur in MODELS else 0, format_func=lambda m: LABELS.get(m, m), key="m_settings_model")
    if pick != cur:
        st.session_state.model_sel = pick
        st.rerun()
    st.toggle("Fast mode", value=bool(st.session_state.get("fast_toggle", False)), key="fast_toggle")
    st.toggle("Deep research (more sources, slower)", value=bool(st.session_state.get("m_deep", False)), key="m_deep")
    st.toggle("Speak replies aloud", value=bool(st.session_state.get("use_voice", True)), key="use_voice")
    st.toggle("Auto-learn from conversations", value=bool(st.session_state.get("m_autolearn", True)), key="m_autolearn")
    st.toggle("HUD sound effects", value=bool(st.session_state.get("m_sfx", True)), key="m_sfx")
    st.slider("HUD volume", 0.0, 1.0, float(st.session_state.get("m_sfx_vol", 0.22)), 0.02, key="m_sfx_vol")
    st.selectbox("Speech recognition language", ["en-US", "en-IN", "en-GB", "te-IN", "hi-IN", "kn-IN", "mr-IN", "ta-IN", "ml-IN", "bn-IN", "gu-IN", "pa-IN", "en-AU", "en-ZA", "es-ES", "fr-FR", "de-DE", "pt-BR", "ja-JP"], index=0, key="stt_lang")
    st.caption("Mobile voice runs on your phone (mic + speaker). Recognition uses a fast speech service; replies use the fastest model path.")
    if st.button("Open memory & data", key="m_open_memory", width="stretch", on_click=_mobile_nav, args=("memory",)):
        pass
    if st.button("Open tap-to-talk fallback", key="m_open_voice", width="stretch", on_click=_mobile_nav, args=("voice",)):
        pass
    st.markdown("#### Personal memory")
    _up = load_user_profile()
    _uname = st.text_input("Your name", value=_up.get("name") or "", placeholder="e.g. Alex", key="m_user_name")
    _upref = st.text_input("Preferences / context", value=_up.get("preferences") or "", placeholder="e.g. I like concise answers; I am learning Python", key="m_user_pref")
    _unotes = st.text_area("Notes", value=_up.get("notes") or "", placeholder="Anything JARVIS should remember", key="m_user_notes", height=64)
    if st.button("Save memory", key="m_user_mem_save", width="stretch"):
        update_user_profile(name=_uname, preferences=_upref, notes=_unotes)
        st.success("Memory saved")
        st.rerun()
    _ctx_txt = get_user_context()
    if _ctx_txt:
        st.caption(f"JARVIS remembers: {_ctx_txt}")
    st.markdown("#### View")
    if st.button("Open desktop version", key="m_desktop_link", width="stretch"):
        st.query_params["view"] = "desktop"
        if "page" in st.query_params:
            del st.query_params["page"]
        st.rerun()


def _mobile_try_intent(prompt: str):
    import datetime as _dt
    p = (prompt or "").strip().lower()
    if not p or len(p) > 120:
        return None
    now = _dt.datetime.now()
    if re.match(r"^(hi|hello|hey|yo|good (morning|afternoon|evening))\b", p) and len(p) < 40:
        return ("reply", "Hello. JARVIS online — how can I help?")
    if re.search(r"\b(time|date)\b", p) and len(p.split()) <= 6 and not any(k in p for k in ("timer", "timezone", "runtime")):
        return ("reply", now.strftime("It's %I:%M %p on %A, %d %B %Y."))
    if "weather" in p and len(p.split()) <= 8 and not any(c in p for c in (" in ", " at ", " for ")):
        w = get_weather_cached()
        return ("reply", f"Bengaluru: {w['temp']:.0f}°C, humidity {w['hum']}%, wind {w['wind']} km/h. High {w['max']:.0f}°, low {w['min']:.0f}°.")
    m = re.match(r"^(?:add|create)\s+(?:a\s+)?task[:\s]+(.+)$", prompt or "", re.I)
    if m:
        title = m.group(1).strip()
        tasks = st.session_state.get("tasks") or load_tasks()
        tasks.append({"title": title, "time": "Today", "done": False})
        st.session_state.tasks = tasks
        save_tasks(tasks)
        return ("reply", f"Added “{title}” to your tasks.")
    if re.match(r"^(?:show|list|what are)\s+(?:my\s+)?tasks\b", p):
        tasks = st.session_state.get("tasks") or load_tasks()
        if not tasks:
            return ("reply", "Your task list is empty.")
        lines = [f"- {'✅' if t.get('done') else '⬜'} {t.get('title', '')}" for t in tasks[:12]]
        return ("reply", "Your tasks:\n" + "\n".join(lines))
    if re.search(r"\b(system|device)\s+(status|stats|usage)\b", p) or re.fullmatch(r"(cpu|ram|memory|disk)( usage)?\??", p):
        try:
            import psutil as _ps
            cpu = _ps.cpu_percent(interval=0.2)
            mem_pct = _ps.virtual_memory().percent
            du = _ps.disk_usage("C:\\" if os.name == "nt" else "/")
            disk = int(du.used / du.total * 100)
            return ("reply", f"Host status — CPU {cpu:.0f}%, RAM {mem_pct:.0f}%, disk {disk}%.")
        except Exception:
            return ("reply", "System status is unavailable right now.")
    m = re.match(r"^(?:open|go to)\s+(chat|voice|camera|media|tasks|weather|system|models|memory|settings)\b", p)
    if m:
        return ("nav", m.group(1))
    if re.fullmatch(r"clear (done|completed) tasks", p):
        tasks = [t for t in (st.session_state.get("tasks") or load_tasks()) if not t.get("done")]
        st.session_state.tasks = tasks
        save_tasks(tasks)
        return ("reply", "Cleared completed tasks.")
    if re.match(r"^(?:what(?:'s| is) my name|do you know my name)\b", p):
        prof = load_user_profile()
        name = (prof.get("name") or "").strip()
        if not name and mem:
            try:
                for mrec in mem.retrieve_memories("user name", 10):
                    txt = mrec.get("text", "")
                    nm = re.search(r"(?:user'?s? name is|my name is)\s+([A-Za-z][A-Za-z .'\-]{0,40})", txt, re.I)
                    if nm:
                        name = nm.group(1).strip().rstrip(".")
                        break
            except Exception:
                name = ""
        if name:
            return ("reply", f"Your name is {name}.")
        return ("reply", "I don't have your name stored right now — tell me “my name is …” and I'll remember it.")
    if re.match(r"^(?:what do you know about me|who am i|what do you remember|do you remember me|show (?:me )?(?:your|my) memory)\b", p):
        prof = load_user_profile()
        bits = []
        if (prof.get("name") or "").strip():
            bits.append(f"Your name is {prof.get('name')}")
        if (prof.get("preferences") or "").strip():
            bits.append(f"preferences: {prof.get('preferences')}")
        if (prof.get("notes") or "").strip():
            bits.append(f"notes: {prof.get('notes')}")
        if mem:
            try:
                learned = [m.get("text", "") for m in mem.retrieve_memories(prompt, 8)]
                for t in learned:
                    if t and all(t not in b for b in bits):
                        bits.append(t)
            except Exception:
                pass
        if not bits:
            return ("reply", "I don't have anything stored about you yet — just talk to me normally and I'll learn.")
        return ("reply", "From memory:\n- " + "\n- ".join(bits[:10]))
    if re.match(r"^(?:forget|delete|erase)\s+(?:everything|all memory|my memory|all data)\b", p):
        if mem:
            try:
                mem.wipe_all()
            except Exception:
                pass
        save_user_profile(dict(DEFAULT_USER_PROFILE))
        return ("reply", "Done. I wiped all local memory, voice clips and snapshots.")
    m = re.match(r"^(?:forget|delete|erase)\s+(?:that\s+|about\s+)?(.+)$", prompt or "", re.I)
    if m and not re.match(r"^(?:it|this|that)$", m.group(1).strip(), re.I):
        q = m.group(1).strip()
        n = 0
        if mem:
            try:
                n = mem.forget_matching(q)
            except Exception:
                n = 0
        # Keep the profile in sync when the user forgets their name.
        try:
            prof = load_user_profile()
            pname = (prof.get("name") or "").strip()
            if pname and "name" in q.lower() and pname.lower() in q.lower():
                prof["name"] = ""
                save_user_profile(prof)
        except Exception:
            pass
        return ("reply", f"Forgotten: “{q}”" + (f" ({n} memory item{'s' if n != 1 else ''})." if n else "."))
    m = re.match(r"^remember\s+(?:that\s+)?(.+)$", prompt or "", re.I)
    if m:
        val = m.group(1).strip()
        prof = load_user_profile()
        if not (prof.get("preferences") or "").strip():
            prof["preferences"] = val
        else:
            prof["notes"] = ((prof.get("notes") or "") + " " + val).strip()
        save_user_profile(prof)
        if mem:
            try:
                mem.add_memory(f"The user asked JARVIS to remember: {val}", "fact", 4)
            except Exception:
                pass
        return ("reply", f"Got it — remembered: {val}")
    m = re.match(r"^(?:plan|make a plan for|create a plan for|organize)\s+my\s+day\b", p)
    if m:
        tasks = st.session_state.get("tasks") or load_tasks()
        open_t = [t for t in tasks if not t.get("done")]
        lines = [f"- {t.get('title')} ({t.get('time')})" for t in open_t[:10]]
        body = "\n".join(lines) if lines else "- No open tasks — enjoy a clear day."
        return ("reply", f"Here's your day plan:\n{body}")
    m = re.match(r"^(?:plan|make a plan for|create a plan for|start plan for)\s+(.+)$", prompt or "", re.I)
    if m:
        goal = m.group(1).strip()
        tasks = st.session_state.get("tasks") or load_tasks()
        tasks.append({"title": f"Plan: {goal}", "time": "Today", "done": False})
        st.session_state.tasks = tasks
        save_tasks(tasks)
        return ("reply", f"Planning “{goal}” — added a plan task. Break it into steps and add each step as its own task.")
    return None


def _mobile_classify_media(prompt: str):
    """Return ('song'|'video', query) for media requests without calling the AI.
    Playback needs a media lookup, not a language model — this is what makes it instant."""
    low = (prompt or "").lower().strip()
    if not low:
        return None, ""
    video_re = r"\b(video|youtube|watch|movie|film|trailer|clip|episode)\b"
    song_re = r"\b(song|songs|music|spotify|track|listen|listen to|blast|sing|singing|playing)\b"
    if re.match(r"^(play|put on|start|listen to|i want to listen to|i wanna hear)\b", low):
        if re.search(video_re, low):
            return "video", low
        return "song", clean_music_query(prompt)
    if re.search(song_re, low):
        return "song", clean_music_query(prompt)
    if re.search(video_re, low):
        return "video", low
    m = re.match(r"^(?:play|put on|add to|queue)\s+(?:album|playlist)\s+(.+)$", low)
    if m:
        return "song", clean_music_query(m.group(1) + " album")
    return None, ""


def _mobile_needs_web(prompt: str) -> bool:
    """Only time-sensitive questions need a live web lookup. Static knowledge is answered
    directly by the fast model — this is the main reason mobile replies were taking 10s."""
    if not is_info_query(prompt):
        return False
    t = (prompt or "").lower()
    return bool(re.search(
        r"\b(news|latest|today|tonight|current|currently|recent|recently|right now|live|breaking|"
        r"update|updates|price|prices|stock|stocks|score|scores|match|matches|election|"
        r"weather|forecast|release|released|launched|who won|how much is|how much does|"
        r"exchange rate|bitcoin|btc|usd|inr|eur)\b", t))


def _mobile_play_song(query: str):
    q = (query or "").strip()
    if not q:
        return "Which song should I play?", None, "media"
    title = _song_title_from_query(q)
    url = ""
    try:
        url = search_youtube(f"{q} song audio") or search_spotify(q)
    except Exception:
        url = ""
    if not url:
        return f"I couldn't find “{title}”. Try a different song name.", None, None
    st.session_state.music_url = url
    st.session_state.music_title = title
    st.session_state.music_query = q
    mh = st.session_state.get("music_history") or []
    mh.append({"url": url, "title": title})
    st.session_state.music_history = mh[-5:]
    st.session_state.music_index = len(st.session_state.music_history) - 1
    return f"Playing “{title}” — tap play in Media.", None, "media"


def _mobile_play_video(prompt: str):
    url = ""
    try:
        url = search_youtube(prompt)
    except Exception:
        url = ""
    if not url:
        return "I couldn't find that video — try a different search.", None, None
    st.session_state.video_url = url
    st.session_state.video_title = _song_title_from_query(prompt)[:80]
    return "Video ready — tap play in Media.", None, "media"


def _mobile_strip_media_tags(reply: str, prompt: str) -> str:
    """Validate any [VIDEO:]/[MUSIC:] URL the model returns, store only real playable media,
    and remove the raw tags from the visible/text-to-speech reply."""
    t = reply or ""
    vm = re.search(r"\[VIDEO:\s*(https?://[^\]\s]+)", t)
    if vm:
        u = vm.group(1).strip()
        try:
            o = requests.get("https://www.youtube.com/oembed", params={"url": u, "format": "json"}, timeout=4)
            if o.status_code == 200:
                st.session_state.video_url = u
                st.session_state.video_title = (o.json().get("title") or st.session_state.get("video_title") or "")[:80]
        except Exception:
            pass
    mm = re.search(r"\[MUSIC:\s*(https?://[^\]\s]+)", t)
    if mm:
        u = mm.group(1).strip()
        if "open.spotify.com/track/" in u:
            try:
                o = requests.get("https://open.spotify.com/oembed", params={"url": u}, timeout=4)
                if o.status_code == 200:
                    st.session_state.music_url = u
                    st.session_state.music_title = o.json().get("title") or st.session_state.get("music_title") or ""
            except Exception:
                pass
        elif "youtube.com/" in u or "youtu.be/" in u:
            st.session_state.music_url = u
    clean = re.sub(r"\[(VIDEO|MUSIC):[^\]]*\]", "", t).strip()
    clean = re.sub(r"^\((?:[^)]*)\)$", "", clean).strip()
    return clean or "🎵 Ready in Media →"


def _mobile_answer(api_key, model, use_fast, prompt):
    intent = _mobile_try_intent(prompt)
    if intent:
        kind, val = intent
        if kind == "nav":
            return f"Opening {val}…", None, val
        return val, None, None

    if _is_correction(prompt):
        prev_a = next((m.get("content", "") for m in reversed(st.session_state.get("msgs", [])) if m.get("role") == "assistant"), "")
        fixed = ""
        if mem:
            try:
                fixed = mem.apply_correction_local(prompt)
                mem.learn_correction_async(api_key, DEFAULT, prev_a, prompt)
            except Exception:
                fixed = ""
        if fixed:
            return f"Corrected — I updated my memory: {fixed}", None, None

    low = (prompt or "").lower()
    hist = st.session_state.get("msgs", [])
    _dom = detect_domain(prompt)
    _pers = get_full_context(prompt, include_previous=len(hist) <= 1)
    msgs = [{"role": "system", "content": build_system_prompt(_dom, _pers, "\nMobile: keep replies under 4 sentences unless the user asks for detail.", lang=st.session_state.get("stt_lang", "en-US"))}]
    for h in hist[-15:-1]:
        msgs.append({"role": h["role"], "content": h["content"]})

    cam_bytes = st.session_state.get("camera_bytes")
    wants_vision = any(k in low for k in ("describe", "scan", "camera", "image")) or low in (
        "describe what you see in camera", "scan this image and describe what you see", "describe what you see")
    has_cam = bool(cam_bytes) and wants_vision

    # Media requests skip the LLM entirely: search + play + jump to Media (~1-2s).
    if not has_cam:
        media_kind, media_query = _mobile_classify_media(prompt)
        if media_kind == "song":
            return _mobile_play_song(media_query)
        if media_kind == "video":
            return _mobile_play_video(prompt)

    if has_cam:
        try:
            import base64 as _b64
            b64s = _b64.b64encode(cam_bytes).decode()
            msgs.append({"role": "user", "content": [
                {"type": "text", "text": VISION_PROMPT + (prompt.strip() or "Describe what you see")},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64s}"}},
            ]})
            st.session_state.camera_bytes = None
        except Exception:
            st.session_state.camera_bytes = None
            msgs.append({"role": "user", "content": prompt})
    else:
        msgs.append({"role": "user", "content": prompt})

    # ---------------------------------------------------------------
    # Web layer: OpenRouter web plugin (search + page reading + citations)
    # with the local scraper as fallback. This is what makes answers
    # grounded even when the model's own knowledge is missing/stale.
    # ---------------------------------------------------------------
    deep_web = bool(st.session_state.get("m_deep"))
    use_web = False
    if not has_cam:
        try:
            use_web = bool(webx.needs_web(prompt, deep=deep_web)) if webx else _mobile_needs_web(prompt)
        except Exception:
            use_web = _mobile_needs_web(prompt)

    if _is_correction(prompt) and msgs and msgs[0].get("role") == "system":
        msgs[0]["content"] += (
            "\nThe user is correcting your previous answer. Acknowledge the correction briefly, "
            "then give the corrected answer. Never repeat the wrong claim."
        )

    if use_web:
        import datetime as _dtw
        note = (
            f"\n\nToday is {_dtw.date.today().isoformat()}. Use live web results; cite sources as (Title — URL)."
            + ("\nDeep research mode: be thorough and structured, with at least 2 cited sources."
               if deep_web else "")
        )
        msgs_web = list(msgs)
        msgs_web[-1] = {"role": "user", "content": (prompt + note) if isinstance(msgs[-1].get("content"), str) else msgs[-1]}
        reply_w, err_w, srcs_w = call_or_online(
            api_key, DEFAULT, msgs_web, 0.2, 1400 if deep_web else 950
        )
        if reply_w and not err_w:
            st.session_state["_last_sources"] = (srcs_w or [])[:6]
            return _mobile_strip_media_tags(reply_w, prompt), None, None
        # Local scraper fallback (real page extraction; no API plugin required).
        wc, srcs = "", []
        try:
            ctx = webx.get_context(prompt, deep=deep_web, budget=6.5) if webx else None
            if ctx:
                wc = ctx.get("context", "") or ""
                srcs = ctx.get("sources", []) or []
        except Exception:
            wc, srcs = "", []
        if wc:
            st.session_state["_last_sources"] = srcs[:6]
            msgs[-1] = {"role": "user", "content": (
                f"{prompt}\n\nLive web results ({_dtw.date.today().isoformat()}):\n{wc}\n\n"
                "Answer using the web results above. Cite sources as (Title — URL)."
            )}

    toks = 2048 if has_cam else 640
    reply, err = call_or(
        api_key,
        FAST if use_fast else model,
        msgs,
        0.2 if has_cam else 0.5,
        toks,
        fast_chat=(not has_cam),
        _has_image=has_cam,
    )
    # If the model admits it doesn't know, ground the answer with the web plugin.
    if reply and not err and not has_cam and not use_web and webx and webx.looks_uncertain(reply):
        reply2, err2, srcs2 = call_or_online(api_key, DEFAULT, msgs, 0.2, 900)
        if reply2 and not err2:
            st.session_state["_last_sources"] = (srcs2 or [])[:6]
            reply = reply2
    if reply and not err:
        reply = _mobile_strip_media_tags(reply, prompt)
    return reply, err, None


def _mobile_generate_pending(api_key, model, use_fast) -> None:
    if not st.session_state.get("_mobile_gen"):
        return
    msgs = st.session_state.get("msgs", [])
    if not msgs or msgs[-1].get("role") != "user":
        st.session_state["_mobile_gen"] = False
        return
    ts = st.session_state.get("_mobile_gen_ts") or 0
    if ts and (time.time() - ts) > 180:
        st.session_state["_mobile_gen"] = False
        msgs.append({"role": "assistant", "content": "⚠️ That reply took too long. Please try again."})
        st.rerun()
    prompt = msgs[-1].get("content", "") or ""
    nav_to = None
    try:
        reply, err, nav_to = _mobile_answer(api_key, model, use_fast, prompt)
    except Exception as e:
        reply, err = "", f"Mobile reply error: {e}"
    _amsg = {"role": "assistant", "content": (reply if not err else f"⚠️ {err}")}
    if reply and not err:
        _amsg["_tts_id"] = _new_tts_id()
        st.session_state["_tts_fresh"] = _amsg["_tts_id"]
    st.session_state.msgs.append(_amsg)
    st.session_state["_sfx_after"] = "error" if err else "reply"
    try:
        if mem:
            page = st.session_state.get("_mobile_page", "")
            mem.log_turn("assistant", reply if not err else f"Error: {err}", "jarvis", page, model)
            if st.session_state.get("_cam_prompt_ts") and (time.time() - float(st.session_state.get("_cam_prompt_ts") or 0) < 180):
                mem.update_latest_snapshot_description(reply or "")
                st.session_state["_cam_prompt_ts"] = 0
            if st.session_state.get("m_autolearn", True) and not nav_to:
                mem.maybe_learn_async(api_key, DEFAULT)
            mem.reflect_async(api_key, DEFAULT)
    except Exception:
        pass
    st.session_state["_mobile_gen"] = False
    st.session_state["_mobile_gen_ts"] = 0
    if len(st.session_state.msgs) > 40:
        st.session_state.msgs = st.session_state.msgs[-30:]
    if nav_to:
        st.session_state["_mobile_page_sel"] = nav_to
    st.rerun()


def _restore_chat_history() -> None:
    """Reload the visible chat history from the persistent memory store after a page reload."""
    if mem is None:
        return
    try:
        if st.session_state.get("msgs"):
            return
        turns = mem.recent_turns(30)
    except Exception:
        turns = []
    if not turns:
        return
    msgs = []
    for t in turns:
        if t.get("role") in ("user", "assistant"):
            msgs.append({"role": t["role"], "content": t["text"]})
    if msgs:
        st.session_state["msgs"] = msgs[-30:]


def _render_mobile_app() -> None:
    api_key = get_key()
    if not valid_key(api_key):
        _mobile_key_gate()
        return
    _restore_chat_history()
    model = st.session_state.get("model_sel") or DEFAULT
    if model not in MODELS:
        model = DEFAULT
    use_fast = bool(st.session_state.get("fast_toggle", False))
    use_voice = bool(st.session_state.get("use_voice", True))
    _qp_page = _qp_str("page", "").strip().lower()
    if _qp_page in MOBILE_PAGES and _qp_page != st.session_state.get("_qp_last_page"):
        st.session_state["_qp_last_page"] = _qp_page
        st.session_state["_mobile_page_sel"] = _qp_page
    page = str(st.session_state.get("_mobile_page_sel") or "").strip().lower()
    if page not in MOBILE_PAGES:
        page = os.getenv("JARVIS_MOBILE_PAGE", "").strip().lower()
    if page not in MOBILE_PAGES:
        page = _qp_page if _qp_page in MOBILE_PAGES else "home"
    st.session_state["_mobile_page_sel"] = page
    st.session_state["_mobile_page"] = page
    # Proactive morning briefing (6:00–9:00) — once per day, composed from memory/tasks/weather
    import datetime as _ddmod2
    _hr = _ddmod2.datetime.now().hour
    if page == "home" and 6 <= _hr <= 9 and not st.session_state.get("_briefed_today") and not st.session_state.get("_mobile_gen"):
        st.session_state["_briefed_today"] = True
        _b_tasks = [t.get("title") for t in (st.session_state.get("tasks") or load_tasks()) if not t.get("done")]
        _b_w = get_weather_cached()
        _brief_body = f"Good morning. Today's briefing — Bengaluru weather is { _b_w['temp']:.0f}°C. " + (
            "Tasks: " + "; ".join(_b_tasks[:6]) if _b_tasks else "No open tasks.")
        _brief = (_brief_body[:600] + " Stay safe, sir.")
        st.session_state.setdefault("msgs", [])
        _amsg = {"role": "assistant", "content": _brief, "_tts_id": _new_tts_id()}
        st.session_state.msgs.append(_amsg)
        st.session_state["_tts_fresh"] = _amsg["_tts_id"]
        _mobile_tts(_brief, _amsg["_tts_id"])
    _mobile_header()
    boot_new = not st.session_state.get("_booted")
    if boot_new:
        st.session_state["_booted"] = True
        _mobile_boot()
    _sfx_event = "boot" if boot_new else str(st.session_state.pop("_sfx_after", "") or "")
    _mobile_sfx(_sfx_event, "thinking" if st.session_state.get("_mobile_gen") else "")
    _mobile_pwa_mount()
    _mobile_clock_mount()
    # If a fresh reply landed on a page that has no voice widget, speak it here once
    # (and never leave stale freshness around to replay an old chat later).
    if page not in ("chat", "voice") and st.session_state.get("_tts_fresh"):
        _la = next((_m for _m in reversed(st.session_state.get("msgs", [])) if _m.get("role") == "assistant"), None)
        if _la and _la.get("_tts_id") and _la.get("_tts_id") == st.session_state.get("_tts_fresh"):
            _mobile_tts(_la.get("content", ""), _la["_tts_id"])
        else:
            st.session_state["_tts_fresh"] = ""
    if page == "home":
        _mobile_page_home()
    elif page == "chat":
        _mobile_page_chat(api_key, model, use_fast, use_voice)
    elif page == "voice":
        _mobile_page_voice(use_voice)
    elif page == "camera":
        _mobile_page_camera()
    elif page == "media":
        _mobile_page_media()
    elif page == "tasks":
        _mobile_page_tasks()
    elif page == "weather":
        _mobile_page_weather()
    elif page == "system":
        _mobile_page_system()
    elif page == "models":
        _mobile_page_models()
    elif page == "memory":
        _mobile_page_memory()
    elif page == "settings":
        _mobile_page_settings(api_key)
    _mobile_generate_pending(api_key, model, use_fast)


def main():
    global _JARVIS_API_KEY
    if "_session_start" not in st.session_state:
        st.session_state["_session_start"] = time.time()
    is_mobile = _is_mobile_view()
    st.set_page_config(page_title="JARVIS AI", page_icon="◉", layout=("centered" if is_mobile else "wide"), initial_sidebar_state="collapsed")
    if is_mobile:
        # Phones get the lightweight HUD (no large background image / video) for fast first paint
        st.markdown(CSS.replace("__BG_URI__", ""), unsafe_allow_html=True)
        st.markdown(MOBILE_CSS, unsafe_allow_html=True)
        _render_mobile_app()
        return
    bg_uri = _bg_data_uri()
    st.markdown(CSS.replace("__BG_URI__", bg_uri), unsafe_allow_html=True)
    # Live video background merged with image background (gui_main.mp4 loop, muted)
    st.markdown("""
    <video autoplay muted loop playsinline style="position:fixed;top:0;left:0;width:100vw;height:100vh;object-fit:cover;z-index:0;opacity:0.32;pointer-events:none;">
      <source src="/static/gui_bg.mp4" type="video/mp4">
    </video>
    <div style="position:fixed;inset:0;background:rgba(5,7,13,0.45);z-index:0;pointer-events:none;"></div>
    """, unsafe_allow_html=True)
    # Handle drag-drop editor save via query param (?layout=...)
    try:
        if "layout" in st.query_params:
            import json as _jl
            _data = st.query_params.get("layout", "")
            if isinstance(_data, list):
                _data = _data[0]
            if _data:
                _panels = _jl.loads(_data)
                # Derive REAL UI column widths + heights from drag positions so real panels move/resize
                _left_x = _panels.get("clock", {}).get("x", 20)
                _center_x = _panels.get("jarvis", {}).get("x", 285)
                _right_x = _panels.get("camera", {}).get("x", 730)
                _cols = [max(0.6, _left_x/200), max(0.8, (_center_x-_left_x)/300), max(0.6, (_right_x-_center_x)/300)]
                _reactor = _panels.get("jarvis", {})
                _chat = _panels.get("chat", {})
                save_layout({"panels": _panels, "columns": _cols, "clock_h": 78, "chat_h": int(_chat.get("h", 240)), "reactor_h": int(_reactor.get("h", 340))})
                st.query_params.clear()
    except Exception:
        pass
    if "edit_layout" not in st.session_state:
        st.session_state.edit_layout = False
    api_key = get_key()
    if not valid_key(api_key):
        st.markdown('<div class="hud" style="max-width:560px;margin:8vh auto;">◉ J.A.R.V.I.S. — enter OpenRouter key (sk-or-v1-...)</div>', unsafe_allow_html=True)
        k = st.text_input("OpenRouter API Key", type="password", placeholder="sk-or-v1-...")
        if st.button("UNLOCK JARVIS", type="primary", use_container_width=True):
            if valid_key(k):
                _JARVIS_API_KEY = k.strip()
                persist_key(k.strip())
                st.rerun()
            else:
                st.error("Invalid key. Must start with sk-or-v1-")
        return

    # Hidden settings — kept for function, displayed via Settings dialog (not left sidebar)
    # NOTE: Model / Fast / Creativity / Max tokens sliders REMOVED from main screen (red X in jarv_upd.png)
    if "model_sel" in st.session_state:
        model = st.session_state.model_sel
    else:
        model = MODELS[0]
    use_fast = st.session_state.get("fast_toggle", False)
    temp = 0.5
    toks = 2048
    use_voice = st.session_state.get("use_voice", True)
    _vc = st.session_state.get("voice_choice")
    voice_choice = _vc[1] if isinstance(_vc, tuple) else (_vc or "en-US-GuyNeural")

    if "active_tab" not in st.session_state:
        st.session_state.active_tab = "Home"

    # Settings popup (inline panel) — API key + model, hidden by default
    if st.session_state.active_tab == "Settings":
        st.markdown('<div class="hud"><div class="ht">Jarvis Settings</div>', unsafe_allow_html=True)
        nk = st.text_input("OpenRouter key", type="password", placeholder="sk-or-v1-...")
        c1, c2 = st.columns(2)
        with c1:
            if st.button("SAVE KEY", use_container_width=True):
                if valid_key(nk):
                    _JARVIS_API_KEY = nk.strip()
                    persist_key(nk.strip())
                    st.success("Saved")
                    st.rerun()
            if st.button("CLEAR", use_container_width=True):
                _JARVIS_API_KEY = ""
                persist_key("")
                st.rerun()
        st.caption(f"Active key: {get_key()[:8]}...{get_key()[-4:] if get_key() else ''}")
        use_fast = st.toggle("Fast mode", value=False, key="fast_toggle")
        st.markdown("---")
        st.markdown("### 🎙️ Human Voice")
        use_voice = st.toggle("Speak every reply aloud (human voice)", value=True, key="use_voice")
        _VOICE_OPTIONS = [
            ("Guy — US English (male)", "en-US-GuyNeural"),
            ("Brian — US English (natural male)", "en-US-BrianNeural"),
            ("Emma — US English (warm female)", "en-US-EmmaNeural"),
            ("Aria — US English (friendly)", "en-US-AriaNeural"),
            ("Jenny — US English (warm)", "en-US-JennyNeural"),
            ("Neerja — Indian English (natural female)", "en-IN-NeerjaNeural"),
            ("Hindi — हिन्दी (Swara — female)", "hi-IN-SwaraNeural"),
            ("Hindi — हिन्दी (Madhur — male)", "hi-IN-MadhurNeural"),
            ("Telugu — తెలుగు (Shruti — female)", "te-IN-ShrutiNeural"),
            ("Telugu — తెలుగు (Mohan — male)", "te-IN-MohanNeural"),
            ("Kannada — ಕನ್ನಡ (Sapna — female)", "kn-IN-SapnaNeural"),
            ("Kannada — ಕನ್ನಡ (Gagan — male)", "kn-IN-GaganNeural"),
        ]
        _vc_state = st.session_state.get("voice_choice")
        if _vc_state is not None and _vc_state not in _VOICE_OPTIONS:
            try:
                del st.session_state["voice_choice"]
            except Exception:
                pass
        voice_choice = st.selectbox(
            "Voice",
            options=_VOICE_OPTIONS,
            format_func=lambda x: x[0],
            index=0,
            key="voice_choice",
        )[1]
        voice_gender = st.select_slider("Voice gender", options=["Auto", "Male", "Female"], key="voice_gender")
        st.caption("Native neural voice for your speech language: Telugu (Shruti/Mohan), Hindi (Swara/Madhur), Kannada (Sapna/Gagan), English (your selected voice). Human pacing, natural pauses and breathing — not a device/robotic voice.")
        if st.button("Close Settings"):
            st.session_state.active_tab = "Home"; st.rerun()
        st.markdown('</div>', unsafe_allow_html=True)

    # Always-on JARVIS mic listener (only when voice replies are enabled)
    if use_voice:
        _ensure_voice_listener()

    # Top bar removed — grid only as in image (no tabs row)

    for key, defaults in [("msgs", []), ("video_url", ""), ("music_url", ""), ("video_big", False), ("music_big", False), ("prompt_input", ""), ("news_date", ""), ("news_title", ""), ("edit_layout", False), ("_voice_dispatch", False)]:
        if key not in st.session_state: st.session_state[key] = defaults

    layout = load_layout()
    # Edit button + editor board REMOVED — layout locked exact as shown (normal dashboard only)
    col_widths = layout.get("columns", [1.0, 1.5, 1.0])

    # Daily news auto-update — fetch fresh video every day, accurate + dated
    today_str = get_daily_date()
    if st.session_state.news_date != today_str:
        try:
            st.session_state.video_url = search_youtube(f"tech news today {today_str}")
            st.session_state.news_title = f"Today's Tech News — {today_str}"
            st.session_state.news_date = today_str
        except Exception:
            pass

    w = get_weather()
    try:
        import psutil as _p; cpu=_p.cpu_percent(interval=0.1); mem=_p.virtual_memory().percent
    except Exception: cpu, mem = 32, 56

    left, center, right = st.columns([1.1, 1.4, 1.1], gap="large")
    st.markdown('<div style="height:4px"></div>', unsafe_allow_html=True)

    with left:
        components.html(clock_html(), height=78)
        import shutil as _sh
        try:
            _du = _sh.disk_usage("C:\\" if os.name == "nt" else "/")
            _storage_pct = int((_du.used / _du.total) * 100)
            _storage_str = f"{_du.used // (1024**3)} GB / {_du.total // (1024**3)} GB"
        except Exception:
            _storage_pct, _storage_str = 56, "287 GB / 512 GB"
        try:
            import subprocess as _sp
            _r = _sp.run(["nvidia-smi", "--query-gpu=utilization.gpu", "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=3)
            _gpu = int(float(_r.stdout.strip().split()[0])) if _r.stdout.strip() else None
        except Exception:
            _gpu = None
        def _gauge(pct, label):
            if pct is None:
                return f'<div style="text-align:center;"><div style="width:64px;height:64px;border-radius:50%;border:4px solid #123;margin:0 auto;display:flex;align-items:center;justify-content:center;font-family:Orbitron,monospace;color:#8aa4bd;">N/A</div><div style="font-size:12px;margin-top:4px;">{label}</div></div>'
            c = 2 * 3.14159 * 28
            off = c * (1 - max(0, min(100, pct)) / 100)
            return f'<div style="text-align:center;"><svg width="64" height="64" viewBox="0 0 64 64"><circle cx="32" cy="32" r="28" fill="none" stroke="#123" stroke-width="5"/><circle cx="32" cy="32" r="28" fill="none" stroke="#00ff88" stroke-width="5" stroke-dasharray="{c:.0f}" stroke-dashoffset="{off:.0f}" stroke-linecap="round" transform="rotate(-90 32 32)"/><text x="32" y="36" text-anchor="middle" font-size="13" font-family="monospace" fill="#00ff88">{pct:.0f}%</text></svg><div style="font-size:12px;margin-top:2px;">{label}</div></div>'
        st.markdown(f'<div class="hud"><div class="ht">System Status</div><div style="display:flex;justify-content:space-around;">{_gauge(cpu, "CPU")}{_gauge(mem, "RAM")}{_gauge(_gpu, "GPU")}</div><div style="display:flex;align-items:center;gap:10px;margin-top:10px;"><span>▣ Storage</span><div style="flex:1;height:8px;background:#123;border-radius:999px;overflow:hidden;"><div style="width:{_storage_pct}%;height:100%;background:#00ff88;"></div></div><span style="color:#8aa4bd;font-size:12px;">{_storage_str}</span></div></div>', unsafe_allow_html=True)
        st.markdown('<div class="hud">', unsafe_allow_html=True)
        _hdr, _arr = st.columns([3, 1], gap="small")
        with _hdr:
            st.markdown(f'<div class="ht" style="margin-bottom:2px;">AI MODELS — USED</div><div style="color:#8aa4bd;font-size:11px;">Active: {LABELS.get(model, model)}</div>', unsafe_allow_html=True)
        with _arr:
            _arrow = "▲" if st.session_state.get("models_expanded") else "▼"
            if st.button(_arrow, key="models_toggle", use_container_width=True):
                st.session_state.models_expanded = not st.session_state.get("models_expanded", False)
                st.rerun()
        if st.session_state.get("models_expanded"):
            for mid in MODELS:
                is_active = (mid == model)
                label = LABELS.get(mid, mid)
                btn_label = f"● {label} — ACTIVE" if is_active else f"○ {label} — FREE"
                if st.button(btn_label, key=f"model_btn_{mid[:18]}", use_container_width=True, type="primary" if is_active else "secondary"):
                    st.session_state.model_sel = mid
                    st.rerun()
        else:
            st.markdown(f'<div style="margin-top:8px;"></div>', unsafe_allow_html=True)
            if st.button(f"● {LABELS.get(model, model)} — ACTIVE", key="model_btn_small", use_container_width=True, type="primary"):
                st.session_state.models_expanded = True
                st.rerun()
        st.markdown('</div>', unsafe_allow_html=True)
        # Now Playing removed (red X in screenshot) — no music cards in left column
        st.markdown(f'<div class="hud"><div class="ht">WEATHER — BENGALURU</div><div style="font-size:28px;color:#00d4ff;">{w["temp"]:.1f}°C</div><div style="color:#8aa4bd;">Partly cloudy · {w["hum"]}% · {w["wind"]} km/h</div></div>', unsafe_allow_html=True)
        # — SPOTIFY PLAYER (allocated space below Weather) —
        _m_url = st.session_state.get("music_url") or ""
        _m_title = st.session_state.get("music_title") or "Ask: play any song"
        _m_id = ""
        _thumb = ""
        _sp_title = _m_title
        _sp_artist = ""
        if _m_url:
            import re as _sp_re
            _mm = _sp_re.search(r"/track/([A-Za-z0-9]{22})", _m_url)
            if _mm:
                _m_id = _mm.group(1)
                # Cache meta — don't re-hit oEmbed on every rerun (was adding 3s per render)
                _cache = st.session_state.get("meta_cache") or {}
                if _m_url in _cache:
                    _sp_title, _sp_artist, _thumb = _cache[_m_url]
                else:
                    try:
                        _o = requests.get("https://open.spotify.com/oembed", params={"url": _m_url}, timeout=2)
                        if _o.status_code == 200:
                            _oj = _o.json()
                            _sp_title = _oj.get("title", _m_title) or _m_title
                            _sp_artist = _oj.get("author_name", "") or ""
                            _thumb = _oj.get("thumbnail_url", "") or ""
                            _cache[_m_url] = (_sp_title, _sp_artist, _thumb)
                            st.session_state["meta_cache"] = _cache
                    except Exception:
                        pass
        # Build track URI history for JS next/prev (Spotify IFrame API loadUri)
        _hist_all = st.session_state.get("music_history") or []
        _hist_uris = []
        for _h in _hist_all:
            try:
                _hm = re.search(r"/track/([A-Za-z0-9]{22})", _h.get("url", "")) if isinstance(_h, dict) else None
                if _hm:
                    _hist_uris.append(f"spotify:track:{_hm.group(1)}")
            except Exception:
                pass
        if _m_id and f"spotify:track:{_m_id}" not in _hist_uris:
            _hist_uris.append(f"spotify:track:{_m_id}")
        import json as _json
        _hist_json = _json.dumps(_hist_uris if _hist_uris else [f"spotify:track:{_m_id}" if _m_id else ""])
        _hist_idx = min(max(0, st.session_state.get("music_index", len(_hist_uris)-1 if _hist_uris else 0)), len(_hist_uris)-1 if _hist_uris else 0)
        if _m_id:
            _art = f'<img src="{_thumb}" style="width:80px;height:80px;border-radius:14px;object-fit:cover;border:2px solid rgba(29,185,84,0.6);box-shadow:0 0 22px rgba(29,185,84,0.35);"/>' if _thumb else '<div style="width:80px;height:80px;border-radius:14px;background:#1DB954;display:flex;align-items:center;justify-content:center;font-size:36px;color:#fff;">♪</div>'
            _artist_line = f'{_sp_artist} • Spotify' if _sp_artist else 'Spotify'
            _sp_html = f"""<style>
body{{margin:0;background:transparent;font-family:system-ui,sans-serif;}}
.sp-card{{background:rgba(6,24,39,0.97);border:1px solid rgba(0,212,255,0.4);border-radius:16px;padding:12px;box-sizing:border-box;height:100%;overflow:hidden;}}
.sp-top{{display:flex;gap:12px;align-items:center;}}
.sp-live{{color:#1DB954;font-size:11px;letter-spacing:2px;font-weight:800;}}
.sp-title{{color:#e8f1ff;font-size:16px;font-weight:800;line-height:1.25;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:220px;}}
.sp-artist{{color:#8aa4bd;font-size:12px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:220px;margin-top:2px;}}
.sp-eq{{display:flex;align-items:flex-end;gap:4px;height:26px;margin-left:auto;}}
.sp-eq span{{width:5px;background:#1DB954;border-radius:2px;animation:eq 0.9s ease-in-out infinite;}}
.sp-eq span:nth-child(1){{height:12px;animation-delay:0s;}} .sp-eq span:nth-child(2){{height:22px;animation-delay:0.2s;}} .sp-eq span:nth-child(3){{height:16px;animation-delay:0.4s;}} .sp-eq span:nth-child(4){{height:24px;animation-delay:0.1s;}}
@keyframes eq{{0%,100%{{transform:scaleY(0.5);}}50%{{transform:scaleY(1.25);}}}}
.sp-prog{{height:8px;background:#123;border-radius:999px;margin-top:10px;overflow:hidden;cursor:pointer;}}
.sp-bar{{height:100%;width:0%;background:linear-gradient(90deg,#1DB954,#00d4ff);border-radius:999px;}}
.sp-time{{display:flex;justify-content:space-between;color:#6b7f95;font-size:11px;margin-top:6px;}}
.sp-ctl{{display:flex;justify-content:center;align-items:center;gap:8px;margin-top:10px;}}
.sp-btn{{background:rgba(255,255,255,0.06);color:#d6e8f5;border:1px solid rgba(255,255,255,0.12);border-radius:999px;min-width:40px;height:40px;font-size:16px;cursor:pointer;display:flex;align-items:center;justify-content:center;}}
.sp-play{{background:#1DB954;color:#fff;border:none;width:56px;height:56px;border-radius:50%;font-size:22px;box-shadow:0 0 24px rgba(29,185,84,0.8);}}
.sp-btn.on{{color:#1DB954;border-color:#1DB954;}}
#sp-iframe{{width:1px;height:1px;border:0;opacity:0;pointer-events:none;}}
#sp-embed{{height:0;overflow:hidden;opacity:0;pointer-events:none;}}
.sp-open{{text-align:center;margin-top:6px;}} .sp-open a{{color:#00d4ff;font-size:12px;}}
</style>
<div class="sp-card">
<div class="sp-top">{_art}<div style="min-width:0;"><div class="sp-live">● NOW PLAYING • SPOTIFY</div><div class="sp-title">{_sp_title}</div><div class="sp-artist">{_artist_line}</div></div><div class="sp-eq"><span></span><span></span><span></span><span></span></div></div>
<div class="sp-prog"><div class="sp-bar" id="sp-bar"></div></div><div class="sp-time"><span id="sp-cur">00:00</span><span id="sp-dur">--:--</span></div>
<div class="sp-ctl">
<button class="sp-btn" id="sp-shuffle" title="Shuffle">🔀</button>
<button class="sp-btn" id="sp-prev" title="Previous">⏮</button>
<button class="sp-btn" id="sp-back" title="Back 10s">⏪</button>
<button class="sp-btn sp-play" id="sp-play" title="Play/Pause">▶</button>
<button class="sp-btn" id="sp-fwd" title="Forward 10s">⏩</button>
<button class="sp-btn" id="sp-next" title="Next">⏭</button>
<button class="sp-btn" id="sp-repeat" title="Repeat">🔁</button>
</div>
<div id="sp-embed"><iframe src="https://open.spotify.com/embed/track/{_m_id}?theme=0" width="1" height="1" frameborder="0" allow="autoplay; clipboard-write; encrypted-media; fullscreen; picture-in-picture" loading="lazy" style="width:1px;height:1px;opacity:0;"></iframe></div>
<div class="sp-open"><a href="{_m_url}" target="_blank">Open in Spotify ↗</a></div>
</div>
<script>
(function(){{
  var tracks = {_hist_json};
  var idx = {_hist_idx};
  var track = tracks[idx] || tracks[0] || 'spotify:track:{_m_id}';
  var playing = false, pos = 0, dur = 0, shuffle = false, repeat = false, player = null;
  var playBtn = document.getElementById('sp-play');
  var bar = document.getElementById('sp-bar');
  var prog = document.querySelector('.sp-prog');
  var cur = document.getElementById('sp-cur');
  var durEl = document.getElementById('sp-dur');
  var embed = document.getElementById('sp-embed');
  function fmt(ms){{ var s = Math.max(0, Math.floor(ms/1000)); return ('0'+Math.floor(s/60)).slice(-2)+':'+('0'+(s%60)).slice(-2); }}
  function setPlaying(v){{ playing = v; playBtn.textContent = playing ? '⏸' : '▶'; }}
  function postToIframe(cmd){{ var f = embed.querySelector('iframe'); if(f && f.contentWindow) f.contentWindow.postMessage(cmd, '*'); }}
  window.onSpotifyIframeApiReady = function(e) {{
    try {{ player = e.createPlayer({{ uri: track, width: '100%', height: 100 }}); }} catch(err) {{ return; }}
    embed.innerHTML = '';
    embed.appendChild(player.element);
    window._sp_player = player;
    function tryPlay(){{ try{{ var p = player.play(); if(p && p.catch) p.catch(function(){{}}); }}catch(err){{}} }}
    player.addListener('ready', function(){{ tryPlay(); setTimeout(tryPlay, 800); }});
    player.addListener('playback_update', function(p) {{
      pos = p.position || 0; dur = p.duration || 0;
      if(dur > 0) {{ bar.style.width = Math.min(100, pos/dur*100) + '%'; cur.textContent = fmt(pos); durEl.textContent = fmt(dur); }}
      setPlaying(!(p.isPaused));
    }});
    player.addListener('end', function(){{ if(repeat){{ player.play(); }} else if(shuffle){{ document.getElementById('sp-next').click(); }} }});
    window._sp_seek = function(ms){{ try{{ player.seekTo(Math.max(0, Math.min(ms, dur||ms))); }}catch(err){{}} }};
    window._sp_load = function(uri){{ try{{ player.loadUri(uri); setTimeout(tryPlay, 400); }}catch(err){{}} }};
  }};
  // Load API AFTER callback defined (avoids race where src executes before callback exists)
  var s = document.createElement('script');
  s.src = 'https://open.spotify.com/embed/iframe-api/v1/';
  s.async = true;
  document.body.appendChild(s);
  // Fallback: if API blocked/unavailable, plain iframe remains playable; custom buttons drive it via postMessage
  setTimeout(function(){{
    if(!window._sp_player) {{
      // progress stays unknown in fallback — hide fake numbers, show native Spotify player progress instead
      if(dur === 0) {{ cur.textContent = '▶ Spotify'; durEl.textContent = 'play below'; bar.style.width = '0%'; }}
    }}
  }}, 4000);
  window._sp_seek = function(ms){{ if(player){{ try{{ player.seekTo(Math.max(0, ms)); }}catch(err){{}} }} else {{ postToIframe({{command:'seek'}}); }} }};
  window._sp_load = function(uri){{ if(player){{ try{{ player.loadUri(uri); }}catch(err){{}} }} else {{ embed.innerHTML = '<iframe src=\"https://open.spotify.com/embed/track/' + uri.split(':').pop() + '?theme=0\" width=\"100%\" height=\"100\" frameborder=\"0\" allow=\"autoplay; clipboard-write; encrypted-media; fullscreen; picture-in-picture\" loading=\"lazy\" style=\"border-radius:10px;\"></iframe>'; }} }};
  playBtn.addEventListener('click', function(){{
    if(player){{ try{{ if(playing) player.pause(); else player.play(); }}catch(err){{}} }}
    else {{ postToIframe({{command:'toggle'}}); setPlaying(!playing); }}
  }});
  document.getElementById('sp-back').addEventListener('click', function(){{ window._sp_seek((pos||0) - 10000); }});
  document.getElementById('sp-fwd').addEventListener('click', function(){{ window._sp_seek((pos||0) + 10000); }});
  document.getElementById('sp-prev').addEventListener('click', function(){{ if(pos > 3000){{ window._sp_seek(0); }} else if(idx > 0){{ idx = idx - 1; window._sp_load(tracks[idx]); }} else{{ window._sp_seek(0); }} }});
  document.getElementById('sp-next').addEventListener('click', function(){{ if(shuffle){{ idx = Math.floor(Math.random()*tracks.length); }} else{{ idx = Math.min(tracks.length-1, idx+1); }} window._sp_load(tracks[idx]); }});
  document.getElementById('sp-shuffle').addEventListener('click', function(){{ shuffle = !shuffle; this.classList.toggle('on', shuffle); }});
  document.getElementById('sp-repeat').addEventListener('click', function(){{ repeat = !repeat; this.classList.toggle('on', repeat); }});
  if(prog){{ prog.addEventListener('click', function(ev){{ if(!dur) return; var r = prog.getBoundingClientRect(); var f = Math.max(0, Math.min(1, (ev.clientX - r.left)/r.width)); window._sp_seek(f*dur); }}); }}
}})();
</script>"""
            components.html(_sp_html, height=240)
            _hist = st.session_state.get("music_history") or []
            _idx = st.session_state.get("music_index", 0)
            if len(_hist) > 1:
                _pc, _nc = st.columns(2)
                with _pc:
                    if st.button("⏮ Prev song", key="sp_prev_btn", use_container_width=True):
                        _idx = max(0, _idx - 1)
                        st.session_state.music_index = _idx
                        _h = _hist[_idx]
                        st.session_state.music_url = _h["url"]; st.session_state.music_title = _h["title"]
                        st.rerun()
                with _nc:
                    if st.button("⏭ Next song", key="sp_next_btn", use_container_width=True):
                        _idx = min(len(_hist) - 1, _idx + 1)
                        st.session_state.music_index = _idx
                        _h = _hist[_idx]
                        st.session_state.music_url = _h["url"]; st.session_state.music_title = _h["title"]
                        st.rerun()
        elif _m_url:
            _yt = None
            import re as _yt_re
            _yvm = _yt_re.search(r"(?:v=|youtu\.be/|/shorts/)([A-Za-z0-9_-]{6,})", _m_url)
            if _yvm:
                _yt = _yvm.group(1)
            if _yt:
                # Title card with art for YouTube audio fallback (Spotify blocked from this region — still plays)
                _yt_title = _m_title or "Song"
                _yt_artist = ""
                _yt_thumb = f"https://i.ytimg.com/vi/{_yt}/hqdefault.jpg"
                try:
                    _yo = requests.get("https://www.youtube.com/oembed", params={"url": _m_url, "format": "json"}, timeout=5)
                    if _yo.status_code == 200:
                        _yj = _yo.json()
                        _yt_title = _yj.get("title", _yt_title) or _yt_title
                        _yt_artist = _yj.get("author_name", "") or ""
                        _yt_thumb = _yj.get("thumbnail_url", _yt_thumb) or _yt_thumb
                except Exception:
                    pass
                _yt_art = f'<img src="{_yt_thumb}" style="width:80px;height:80px;border-radius:14px;object-fit:cover;border:2px solid rgba(29,185,84,0.6);box-shadow:0 0 22px rgba(29,185,84,0.35);"/>' if _yt_thumb else '<div style="width:80px;height:80px;border-radius:14px;background:#1DB954;display:flex;align-items:center;justify-content:center;font-size:36px;color:#fff;">♪</div>'
                _yt_line = f'{_yt_artist} • YouTube' if _yt_artist else 'YouTube'
                # Next-song history for YouTube audio controls (YouTube IDs only)
                _yt_hist = []
                for _h in (st.session_state.get("music_history") or []):
                    if isinstance(_h, dict):
                        _hm = re.search(r"(?:v=|youtu\.be/|/shorts/)([A-Za-z0-9_-]{6,})", _h.get("url", ""))
                        if _hm:
                            _yt_hist.append(_hm.group(1))
                if _yt and _yt not in _yt_hist:
                    _yt_hist.append(_yt)
                _yt_hist_json = _json.dumps(_yt_hist if _yt_hist else [_yt])
                _yt_html = f"""<style>
body{{margin:0;background:transparent;font-family:system-ui,sans-serif;}}
.sp-card{{background:rgba(6,24,39,0.97);border:1px solid rgba(0,212,255,0.4);border-radius:16px;padding:12px;box-sizing:border-box;height:100%;overflow:hidden;}}
.sp-top{{display:flex;gap:12px;align-items:center;}}
.sp-live{{color:#1DB954;font-size:11px;letter-spacing:2px;font-weight:800;}}
.sp-title{{color:#e8f1ff;font-size:16px;font-weight:800;line-height:1.25;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:220px;}}
.sp-artist{{color:#8aa4bd;font-size:12px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:220px;margin-top:2px;}}
.sp-eq{{display:flex;align-items:flex-end;gap:4px;height:26px;margin-left:auto;}}
.sp-eq span{{width:5px;background:#1DB954;border-radius:2px;animation:eq 0.9s ease-in-out infinite;}}
.sp-eq span:nth-child(1){{height:12px;animation-delay:0s;}} .sp-eq span:nth-child(2){{height:22px;animation-delay:0.2s;}} .sp-eq span:nth-child(3){{height:16px;animation-delay:0.4s;}} .sp-eq span:nth-child(4){{height:24px;animation-delay:0.1s;}}
@keyframes eq{{0%,100%{{transform:scaleY(0.5);}}50%{{transform:scaleY(1.25);}}}}
.sp-ctl{{display:flex;justify-content:center;align-items:center;gap:10px;margin-top:12px;}}
.sp-btn{{background:rgba(255,255,255,0.06);color:#d6e8f5;border:1px solid rgba(255,255,255,0.12);border-radius:999px;min-width:44px;height:44px;font-size:18px;cursor:pointer;display:flex;align-items:center;justify-content:center;}}
.sp-play{{background:#1DB954;color:#fff;border:none;width:56px;height:56px;border-radius:50%;font-size:22px;box-shadow:0 0 24px rgba(29,185,84,0.8);}}
#yt-player{{width:1px;height:1px;opacity:0;pointer-events:none;}}
</style>
<div class="sp-card">
<div class="sp-top">{_yt_art}<div style="min-width:0;"><div class="sp-live">● NOW PLAYING • SONG</div><div class="sp-title">{_yt_title}</div><div class="sp-artist">{_yt_line}</div></div><div class="sp-eq"><span></span><span></span><span></span><span></span></div></div>
<div class="sp-ctl">
<button class="sp-btn" id="yt-prev" title="Previous">⏮</button>
<button class="sp-btn" id="yt-back" title="Back 10s">⏪</button>
<button class="sp-btn sp-play" id="yt-play" title="Play/Pause">⏸</button>
<button class="sp-btn" id="yt-fwd" title="Forward 10s">⏩</button>
<button class="sp-btn" id="yt-next" title="Next song">⏭</button>
</div>
<div id="yt-player"></div>
</div>
<script>
(function(){{
  var hist = {_yt_hist_json};
  var idx = hist.indexOf('{_yt}');
  if(idx < 0) idx = hist.length - 1;
  var playing = true;
  var player = null;
  var playBtn = document.getElementById('yt-play');
  function setPlaying(v){{ playing = v; playBtn.textContent = playing ? '⏸' : '▶'; }}
  window.onYouTubeIframeAPIReady = function() {{
    player = new YT.Player('yt-player', {{
      width: '1', height: '1',
      videoId: '{_yt}',
      playerVars: {{ 'autoplay': 1, 'playsinline': 1, 'rel': 0, 'modestbranding': 1 }},
      events: {{
        'onReady': function(e){{ try{{ e.target.playVideo(); }}catch(err){{}} }},
        'onStateChange': function(e){{ if(e.data === YT.PlayerState.PLAYING) setPlaying(true); else if(e.data === YT.PlayerState.PAUSED) setPlaying(false); }}
      }}
    }});
    window._yt_player = player;
  }};
  var tag = document.createElement('script');
  tag.src = 'https://www.youtube.com/iframe_api';
  document.body.appendChild(tag);
  function seekRel(sec){{ if(player && player.seekTo){{ try{{ player.seekTo(Math.max(0, player.getCurrentTime() + sec), true); }}catch(err){{}} }} }}
  playBtn.addEventListener('click', function(){{
    if(!player) return;
    try{{ if(playing){{ player.pauseVideo(); }} else {{ player.playVideo(); }} }}catch(err){{}}
  }});
  document.getElementById('yt-back').addEventListener('click', function(){{ seekRel(-10); }});
  document.getElementById('yt-fwd').addEventListener('click', function(){{ seekRel(10); }});
  document.getElementById('yt-prev').addEventListener('click', function(){{
    if(player && player.getCurrentTime && player.getCurrentTime() > 3){{ try{{ player.seekTo(0, true); }}catch(err){{}} }}
    else if(idx > 0){{ idx = idx - 1; try{{ player.loadVideoById(hist[idx]); }}catch(err){{}} }}
    else if(player){{ try{{ player.seekTo(0, true); }}catch(err){{}} }}
  }});
  document.getElementById('yt-next').addEventListener('click', function(){{
    if(idx < hist.length - 1){{ idx = idx + 1; try{{ player.loadVideoById(hist[idx]); }}catch(err){{}} }}
    else if(player){{ try{{ player.playVideo(); }}catch(err){{}} }}
  }});
}})();
</script>"""
                components.html(_yt_html, height=220)
            else:
                components.html("""<style>body{margin:0;background:transparent;} .box{background:rgba(6,24,39,0.95);border:1px solid rgba(0,212,255,0.35);border-radius:14px;padding:24px;text-align:center;box-sizing:border-box;min-height:170px;} .logo{width:72px;height:72px;margin:0 auto;background:#1DB954;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:34px;color:#fff;} .t{color:#e8f1ff;font-size:16px;font-weight:700;margin-top:10px;} .s{color:#8aa4bd;font-size:13px;margin-top:4px;}</style><div class="box"><div class="logo">♫</div><div class="t">Spotify Player</div><div class="s">Ask Jarvis — <b>play any song</b> — it auto-plays here (Spotify only)</div></div>""", height=200)
        else:
            # Songs -> Spotify only. Never show a video inside the Spotify card (videos belong in the right YouTube player).
            components.html("""<style>body{margin:0;background:transparent;} .box{background:rgba(6,24,39,0.95);border:1px solid rgba(0,212,255,0.35);border-radius:14px;padding:24px;text-align:center;box-sizing:border-box;min-height:170px;} .logo{width:72px;height:72px;margin:0 auto;background:#1DB954;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:34px;color:#fff;} .t{color:#e8f1ff;font-size:16px;font-weight:700;margin-top:10px;} .s{color:#8aa4bd;font-size:13px;margin-top:4px;}</style><div class="box"><div class="logo">♫</div><div class="t">Spotify Player</div><div class="s">Ask Jarvis — <b>play any song</b> — it auto-plays here (Spotify only)</div></div>""", height=200)

    with center:
        components.html(reactor_html(), height=240)
        # Mic status icon — reflects listening / thinking / sleeping state
        components.html(mic_status_html("thinking" if st.session_state.get("_generating_reply") else (_JARVIS_STATE.get("state") or "sleeping")), height=84)
        # ALWAYS-ON JARVIS MIC: background sounddevice capture + adaptive noise gate + VAD + wake word/clap-snap.
        # No mic button. Listens 24/7 -> sleeps until wake word / clap / snap -> dispatches commands via _CMD_Q.
        # Chat history (visible, scrollable) — above Hey Jarvis bar
        with st.container(height=220, border=True):
            for m in st.session_state.msgs:
                with st.chat_message(m["role"]):
                    import re as _re
                    content = m.get("content", "") or ""
                    # Strip control/garbage chars but keep readable text (emojis, punctuation, letters)
                    content = re.sub(r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F-\x9F]", " ", content)
                    clean = _re.sub(r"\[(VIDEO|MUSIC):\s*https?://[^\]]+\]", "", content).strip() or "🎵 Playing in panel →"
                    st.markdown(clean)
            # ChatGPT-style thinking indicator — user sees it while the AI call is running
            if st.session_state.get("_generating_reply"):
                with st.chat_message("assistant"):
                    st.markdown("⚡ **JARVIS is thinking...**")
        # Listening / sleeping status — printed in the chat section so you always know what's happening
        _mic_state_txt = ("LISTENING — awaiting your command…" if _JARVIS_STATE.get("state") == "listening" else "SLEEPING — say 'Jarvis' or clap/snap to wake me…")
        st.markdown(f"🎙️ **JARVIS:** {_mic_state_txt}")
        # Human voice reply box — last assistant answer speaks + types together
        if use_voice and st.session_state.msgs:
            last_assistant = next((m for m in reversed(st.session_state.msgs) if m.get("role") == "assistant"), None)
            if last_assistant:
                txt = last_assistant.get("content", "")
                import hashlib as _hl
                _say_lang = speech_lang_for(txt, str(st.session_state.get("stt_lang") or "en-US"))
                _say_voice = voice_for_lang(_say_lang, st.session_state.get("voice_gender", "auto"), voice_choice)
                _tts_id = last_assistant.get("_tts_id", "")
                _fresh = bool(_tts_id) and st.session_state.get("_tts_fresh") == _tts_id
                if _fresh:
                    st.session_state["_tts_fresh"] = ""
                _vk = _hl.md5(((txt or "") + "|" + _say_voice + "|" + (_tts_id or "old")).encode()).hexdigest()
                if "_VOICE_BG_CACHE" not in globals():
                    globals()["_VOICE_BG_CACHE"] = {}
                if "_VOICE_GENERATING" not in globals():
                    globals()["_VOICE_GENERATING"] = set()
                _bg = globals()["_VOICE_BG_CACHE"]
                _generating = globals()["_VOICE_GENERATING"]
                b64 = _bg.get(_vk)
                # Lazy TTS: render immediately with browser voice (instant), generate Edge audio in background
                if _fresh and not b64 and _vk not in _generating and txt:
                    _generating.add(_vk)
                    def _bg_gen(_txt=txt, _vk=_vk, _vc=_say_voice, _lg=_say_lang):
                        try:
                            _ab = synthesize_human_speech(_txt, voice=_vc, gender="auto", lang=_lg)
                            import base64 as _b64m
                            _bg[_vk] = _b64m.b64encode(_ab).decode()
                        except Exception:
                            pass
                        finally:
                            _generating.discard(_vk)
                    import threading as _th
                    _th.Thread(target=_bg_gen, daemon=True).start()
                _speak_token = _tts_id or _hl.md5(((txt or "") + "|" + _say_voice).encode()).hexdigest()
                components.html(voice_html(humanize_for_speech(txt, lang=_say_lang), b64, _say_lang, _speak_token, _fresh), height=0)
        if "prompt_input" not in st.session_state: st.session_state.prompt_input = ""
        with st.form("jarvis_form", clear_on_submit=True):
            c1, c2 = st.columns([5, 1])
            with c1:
                prompt = st.text_input("Hey Jarvis...", value=st.session_state.prompt_input, key="jarvis_prompt", label_visibility="collapsed", placeholder="Hey Jarvis... (Enter sends)")
                st.caption("Ask for news/video/songs — plays in right panels")
            with c2:
                sent = st.form_submit_button("➤", type="primary", use_container_width=True)
    with right:
        # Camera — borderless, no words, visuals fill the spot (as requested)
        cam = st.camera_input("Take photo", key="ai_camera_input", label_visibility="collapsed")
        if cam is not None:
            try:
                st.session_state.camera_bytes = cam.getvalue()
            except Exception:
                pass
        ic1, ic2, ic3, ic4 = st.columns(4)
        with ic1:
            if st.button("📷", key="cam_photo2", use_container_width=True): st.info("Photo captured — analyze via Hey Jarvis (OCR/Vision)")
        with ic2:
            if st.button("🎥", key="cam_video2", use_container_width=True): st.session_state.prompt_input = "Describe what you see in camera"
        with ic3:
            if st.button("⤢", key="cam_expand2", use_container_width=True): st.info("Camera preview 460×258 (16:9) — face box centered")
        with ic4:
            if st.button("◎", key="cam_scan2", use_container_width=True): st.session_state.prompt_input = "Scan this image and describe what you see"
        st.markdown('<div class="hud">', unsafe_allow_html=True)
        v_url = st.session_state.video_url or ""
        if v_url:
            import re as _re
            m = _re.search(r"(?:v=|youtu\.be/|/shorts/)([A-Za-z0-9_-]{6,})", v_url)
            if m:
                h = 640 if st.session_state.video_big else 296
                components.html(f'<iframe width="100%" height="{h}" src="https://www.youtube-nocookie.com/embed/{m.group(1)}?rel=0" frameborder="0" allow="fullscreen; encrypted-media" allowfullscreen style="border-radius:8px;"></iframe><div style="display:flex;justify-content:space-between;align-items:center;margin-top:6px;"><span style="color:#8aa4bd;font-size:12px;">▶ Click play inside player for sound</span><a href="{v_url}" target="_blank" style="color:#00d4ff;font-size:12px;">Watch on YouTube ↗</a></div>', height=h+36)
        else:
            components.html('<div style="text-align:center;padding:28px 0 18px 0;"><div style="width:64px;height:46px;margin:0 auto;background:#FF0000;border-radius:10px;display:flex;align-items:center;justify-content:center;"><span style="color:#fff;font-size:22px;">▶</span></div><div style="color:#8aa4bd;font-size:13px;margin-top:6px;">YouTube — Daily news updates automatically</div></div>', height=110)
        # Expand Video button removed (per request)
        st.markdown('</div>', unsafe_allow_html=True)
        st.markdown('<div class="hud"><div class="ht">Tasks — To-Do List</div>', unsafe_allow_html=True)
        if "tasks" not in st.session_state:
            st.session_state.tasks = load_tasks()
        for idx, task in enumerate(list(st.session_state.tasks)):
            new_done = st.checkbox(f"{task['title']} — {task['time']}", task["done"], key=f"task_{idx}")
            if new_done != task["done"]:
                st.session_state.tasks[idx]["done"] = new_done
                save_tasks(st.session_state.tasks)
        new_task = st.text_input("Add task title", placeholder="+ Add Task", key="new_task_title")
        add_col, del_col = st.columns(2)
        with add_col:
            if st.button("+ Add Task", use_container_width=True, key="add_task_btn"):
                if new_task.strip():
                    st.session_state.tasks.append({"title": new_task.strip(), "time": "09:00 PM", "done": False})
                    save_tasks(st.session_state.tasks); st.rerun()
        with del_col:
            if st.button("Clear Done", use_container_width=True, key="del_task_btn"):
                st.session_state.tasks = [t for t in st.session_state.tasks if not t["done"]]
                save_tasks(st.session_state.tasks); st.rerun()
        st.markdown('</div>', unsafe_allow_html=True)

    # Voice (always-on mic) command dispatch — pull recognized commands from the listener queue
    _voice_cmd = None
    if not st.session_state.get("_voice_dispatch", False):
        try:
            _voice_cmd = _CMD_Q.get_nowait()
        except Exception:
            _voice_cmd = None
    if _voice_cmd:
        st.session_state.jarvis_prompt = _voice_cmd
        st.session_state["_voice_dispatch"] = True

    # Send logic
    if sent or st.session_state.get("_voice_dispatch", False):
        if st.session_state.get("_voice_dispatch", False):
            st.session_state["_voice_dispatch"] = False
        final_prompt = (st.session_state.get("jarvis_prompt") or prompt or "").strip()
        eff_model = FAST if use_fast else model
        low = final_prompt.lower()
        # Exclusive routing: songs -> Spotify only, videos -> YouTube only
        _video_words = ("video", "news", "watch", "youtube", "show me", "movie", "film", "trailer")
        _song_words = ("song", "music", "spotify", "track", "listen", "blast", "sing", "playing", "songs", "latest song")
        _has_video = any(k in low for k in _video_words)
        _has_song = any(k in low for k in _song_words)
        if _has_video:
            is_video, is_song = True, False
        elif _has_song:
            is_video, is_song = False, True
        elif "play" in low:
            _cq0 = clean_music_query(final_prompt)
            is_song = bool(_known_track_for(_cq0))
            is_video = not is_song
        else:
            is_video, is_song = False, False
        if not final_prompt:
            st.warning("Type or speak a command first.")
            st.session_state.prompt_input = ""
            st.rerun()
        else:
            import concurrent.futures as _cf
            # Build msgs (trimmed history + optional camera image + web context)
            _dom_d = detect_domain(final_prompt)
            msgs = [{"role": "system", "content": build_system_prompt(_dom_d, get_full_context(final_prompt, include_previous=len(st.session_state.msgs) <= 1), lang=st.session_state.get("stt_lang", "en-US"))}]
            for h in st.session_state.msgs[-6:]:
                msgs.append({"role": h["role"], "content": h["content"]})
            _cam_bytes = st.session_state.get("camera_bytes")
            _wants_vision = any(k in low for k in ("describe", "scan", "camera", "image")) or low in ("describe what you see in camera", "scan this image and describe what you see", "describe what you see")
            _has_cam = bool(_cam_bytes) and _wants_vision
            if _has_cam:
                try:
                    import base64 as _b64
                    _b64s = _b64.b64encode(_cam_bytes).decode()
                    _vision_q = (final_prompt.strip() if final_prompt.strip() else "Describe what you see")
                    msgs.append({"role": "user", "content": [{"type": "text", "text": VISION_PROMPT + _vision_q}, {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{_b64s}"}}]})
                    st.session_state.camera_bytes = None
                except Exception:
                    st.session_state.camera_bytes = None
                    msgs.append({"role": "user", "content": final_prompt})
            else:
                msgs.append({"role": "user", "content": final_prompt})
            # Append user message immediately so it appears in chat instantly
            st.session_state.msgs.append({"role": "user", "content": final_prompt})
            try:
                if mem:
                    mem.log_turn("user", final_prompt, "chat", "desktop", st.session_state.get("model_sel", ""))
            except Exception:
                pass
            st.session_state.prompt_input = ""
            # Trigger immediate rerun to show user message in chat
            st.rerun()
    # Self-heal: if _generating_reply is stuck True from a previous crash, reset it so the page can't be stuck forever
    # Voice-level clarification request (e.g. "I didn't understand") coming from the mic listener thread
    _ask_txt = _JARVIS_ASK_ME["text"]
    if _ask_txt:
        _JARVIS_ASK_ME["text"] = ""
        st.session_state.msgs.append({"role": "assistant", "content": _ask_txt, "_tts_id": _new_tts_id()})
        st.session_state["_tts_fresh"] = st.session_state.msgs[-1]["_tts_id"]
    if st.session_state.get("_generating_reply"):
        st.session_state._generating_reply = False
    # Handle assistant response generation (runs on next render after user msg is shown)
    if st.session_state.msgs and st.session_state.msgs[-1].get("role") == "user" and not st.session_state.get("_generating_reply"):
        st.session_state._generating_reply = True
        final_prompt = st.session_state.msgs[-1]["content"]
        low = final_prompt.lower()
        # Exclusive routing
        _video_words = ("video", "news", "watch", "youtube", "show me", "movie", "film", "trailer")
        _song_words = ("song", "music", "spotify", "track", "listen", "blast", "sing", "playing", "songs", "latest song")
        _has_video = any(k in low for k in _video_words)
        _has_song = any(k in low for k in _song_words)
        if _has_video:
            is_video, is_song = True, False
        elif _has_song:
            is_video, is_song = False, True
        elif "play" in low:
            # "play shape of you" is a song request unless explicit video words were used above.
            is_song, is_video = True, False
        else:
            is_video, is_song = False, False
        eff_model = FAST if use_fast else model
        # Build msgs for AI call
        _dom_d2 = detect_domain(final_prompt)
        msgs = [{"role": "system", "content": build_system_prompt(_dom_d2, get_full_context(final_prompt, include_previous=len(st.session_state.msgs) <= 1), lang=st.session_state.get("stt_lang", "en-US"))}]
        for h in st.session_state.msgs[-7:-1]:  # skip the last user msg we just added
            msgs.append({"role": h["role"], "content": h["content"]})
        _cam_bytes = st.session_state.get("camera_bytes")
        _wants_vision = any(k in low for k in ("describe", "scan", "camera", "image")) or low in ("describe what you see in camera", "scan this image and describe what you see", "describe what you see")
        _has_cam = bool(_cam_bytes) and any(k in low for k in ("describe", "scan", "camera", "image"))
        if _has_cam:
            try:
                import base64 as _b64
                _b64s = _b64.b64encode(_cam_bytes).decode()
                _vision_q = (st.session_state.msgs[-1]["content"].strip() if st.session_state.msgs[-1]["content"].strip() else "Describe what you see")
                msgs.append({"role": "user", "content": [{"type": "text", "text": VISION_PROMPT + _vision_q}, {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{_b64s}"}}]})
                st.session_state.camera_bytes = None
            except Exception:
                st.session_state.camera_bytes = None
                msgs.append({"role": "user", "content": final_prompt})
        else:
            # CRITICAL: the current user message MUST be included — otherwise the AI sees only old history and answers the previous question
            msgs.append({"role": "user", "content": final_prompt})
        # Parallel: web search + media search + AI call — all start together
        import concurrent.futures as _cf
        with _cf.ThreadPoolExecutor(max_workers=4) as _ex:
            _safe_q = is_info_query(final_prompt)
            _fweb = _ex.submit(desktop_web_lookup, final_prompt) if (_safe_q and not is_video and not is_song and not _has_cam) else None
            _fv = _ex.submit(search_youtube, final_prompt) if is_video else None
            _clean_for_song = clean_music_query(final_prompt) if is_song else ""
            # Prefer full-song YouTube audio first (full-length playback, no 30s Spotify preview limit)
            _fs = _ex.submit(lambda: (search_youtube(f"{_clean_for_song} song audio") or search_spotify(_clean_for_song)) if is_song else "", ) if is_song else None
            _fa = _ex.submit(call_or, api_key, eff_model, msgs, 0.2 if _has_cam else (0.5 if use_fast else temp), 2048 if _has_cam else (640 if use_fast else 1024), fast_chat=(not is_video and not is_song and not _has_cam), _has_image=_has_cam)
            reply, err = _fa.result()
            # Apply web results if they came back in time
            if _fweb:
                try:
                    _wc = _fweb.result(timeout=0.5) if _fweb.done() else ""
                except Exception:
                    _wc = ""
                if _wc:
                    try:
                        # Re-run AI with web context
                        reply2, err2 = call_or(api_key, eff_model, msgs + [{"role": "user", "content": f"{final_prompt}\n\n{_wc}\n\nAnswer using the web results above with citations (Title — URL) and today's date."}], 0.2 if _has_cam else (0.5 if use_fast else temp), 2048 if _has_cam else (640 if use_fast else 1024), fast_chat=(not is_video and not is_song and not _has_cam), _has_image=_has_cam)
                        if not err2 and reply2:
                            reply = reply2
                    except Exception:
                        pass
            # If the model admits it doesn't know, ground it with the OpenRouter web plugin.
            if reply and not err and not _has_cam and not is_video and not is_song and webx and webx.looks_uncertain(reply):
                try:
                    _r2, _e2, _ = call_or_online(api_key, DEFAULT, msgs, 0.2, 950)
                    if _r2 and not _e2:
                        reply = _r2
                except Exception:
                    pass
            # Apply media results
            if is_video and _fv:
                try:
                    _yv = _fv.result(timeout=10)
                except Exception:
                    _yv = ""
                if _yv:
                    st.session_state.video_url = _yv
            if is_song:
                _clean_for_song = clean_music_query(final_prompt)
                _known_url = _known_track_for(_clean_for_song)
                _title_match = next((k.title() for k, v in KNOWN_TRACKS.items() if v in _known_url), "")
                st.session_state.music_title = (_title_match or _song_title_from_query(_clean_for_song) or final_prompt or "Your Song")
                _new_mu = ""
                if _fs:
                    try:
                        _new_mu = _fs.result(timeout=10)
                    except Exception:
                        _new_mu = ""
                if _new_mu:
                    st.session_state.music_url = _new_mu
                    _hist = st.session_state.get("music_history") or []
                    _hist.append({"url": _new_mu, "title": st.session_state.music_title})
                    st.session_state.music_history = _hist[-5:]
                    st.session_state.music_index = len(st.session_state.music_history) - 1
        # Streaming response: show tokens as they arrive
        if not err:
            # We already have the full reply, but for streaming feel we can append it in chunks
            # For true streaming, we'd need call_or to support stream=True yield, but we have the full reply
            # So we'll simulate streaming by showing it in the next rerun
            _amsg = {"role": "assistant", "content": reply, "_tts_id": _new_tts_id()}
            st.session_state.msgs.append(_amsg)
            st.session_state["_tts_fresh"] = _amsg["_tts_id"]
            try:
                if mem:
                    mem.log_turn("assistant", reply, "jarvis", "desktop", st.session_state.get("model_sel", ""))
                    if st.session_state.get("m_autolearn", True):
                        mem.maybe_learn_async(api_key, DEFAULT)
                    mem.reflect_async(api_key, DEFAULT)
            except Exception:
                pass
        else:
            st.session_state.msgs.append({"role": "assistant", "content": f"⚠️ {err}"})
        # Handle AI-provided media tags (validates Spotify/YouTube links from the reply)
        if not err and reply:
            import re as _reM
            low = final_prompt.lower()
            _video_words2 = ("video", "news", "watch", "youtube", "show me", "movie", "film", "trailer")
            if any(k in low for k in _video_words2):
                vm = _reM.search(r"\[VIDEO:\s*(https?://[^\]\s]+)", reply)
                if vm:
                    try:
                        _vo = requests.get("https://www.youtube.com/oembed", params={"url": vm.group(1).strip(), "format": "json"}, timeout=6)
                        if _vo.status_code == 200:
                            st.session_state.video_url = vm.group(1).strip()
                    except Exception:
                        pass
            else:
                mm2 = _reM.search(r"\[MUSIC:\s*(https?://[^\]\s]+)", reply)
                if mm2:
                    m_id = _reM.search(r"/track/([A-Za-z0-9]{22})", mm2.group(1))
                    if m_id:
                        try:
                            _o = requests.get("https://open.spotify.com/oembed", params={"url": mm2.group(1).strip()}, timeout=6)
                            if _o.status_code == 200:
                                st.session_state.music_url = mm2.group(1).strip()
                        except Exception:
                            pass
        st.session_state._generating_reply = False
        st.rerun()

    # Bottom taskbar strip removed (red X at bottom in screenshot)


if __name__ == "__main__":
    main()

