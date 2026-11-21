"""JARVIS long-term memory engine.

Stores every turn, extracts durable personal facts with a fast LLM pass,
retrieves relevant memories for prompts, saves voice clips / camera snapshots,
and supports self-correction + daily reflection.

Everything is local (SQLite + memory_media/). No permission prompts.
"""
from __future__ import annotations

import difflib
import json
import re
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable

APP_DIR = Path(__file__).resolve().parent
DB_PATH = APP_DIR / "jarvis_memory.db"
MEDIA_DIR = APP_DIR / "memory_media"
MEDIA_VOICE = MEDIA_DIR / "voice"
MEDIA_SNAPSHOTS = MEDIA_DIR / "snapshots"

API_URL = "https://openrouter.ai/api/v1/chat/completions"

_LEARN_LOCK = threading.Lock()
_LEARN_GEN = 0
_GEN_LOCK = threading.Lock()
_MAX_MEMORIES = 400
_MAX_MEDIA_PER_KIND = 500

_KINDS = {
    "identity", "preference", "goal", "project", "routine",
    "person", "date", "fact", "surrounding",
}

_STOP = {
    "the", "a", "an", "and", "or", "but", "if", "then", "than", "that", "this",
    "these", "those", "is", "are", "was", "were", "be", "been", "being", "to",
    "of", "in", "on", "at", "for", "with", "by", "from", "as", "it", "its",
    "i", "me", "my", "we", "our", "you", "your", "he", "she", "they", "them",
    "do", "does", "did", "have", "has", "had", "will", "would", "can", "could",
    "should", "what", "who", "where", "when", "why", "how", "about", "just",
    "very", "really", "also", "not", "no", "yes", "user", "jarvis",
}


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------
@contextmanager
def _db():
    c = sqlite3.connect(DB_PATH, timeout=8)
    c.row_factory = sqlite3.Row
    try:
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA busy_timeout=8000")
        yield c
        c.commit()
    finally:
        c.close()


def init_db() -> None:
    MEDIA_VOICE.mkdir(parents=True, exist_ok=True)
    MEDIA_SNAPSHOTS.mkdir(parents=True, exist_ok=True)
    with _db() as c:
        c.executescript(
            """
            CREATE TABLE IF NOT EXISTS turns (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts REAL NOT NULL,
                role TEXT NOT NULL,
                text TEXT NOT NULL,
                source TEXT DEFAULT 'chat',
                page TEXT DEFAULT '',
                model TEXT DEFAULT ''
            );
            CREATE INDEX IF NOT EXISTS idx_turns_ts ON turns(ts);

            CREATE TABLE IF NOT EXISTS memories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                kind TEXT NOT NULL DEFAULT 'fact',
                text TEXT NOT NULL,
                importance INTEGER NOT NULL DEFAULT 3,
                created REAL NOT NULL,
                updated REAL NOT NULL,
                last_used REAL DEFAULT 0,
                uses INTEGER DEFAULT 0,
                active INTEGER DEFAULT 1,
                superseded_by INTEGER DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS idx_mem_active ON memories(active);
            CREATE INDEX IF NOT EXISTS idx_mem_kind ON memories(kind);

            CREATE TABLE IF NOT EXISTS summaries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                day TEXT UNIQUE NOT NULL,
                text TEXT NOT NULL,
                created REAL NOT NULL
            );

            CREATE TABLE IF NOT EXISTS media (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                kind TEXT NOT NULL,
                path TEXT NOT NULL,
                description TEXT DEFAULT '',
                created REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_media_kind ON media(kind);

            CREATE TABLE IF NOT EXISTS meta (
                key TEXT PRIMARY KEY,
                value TEXT
            );
            """
        )


init_db()


def _now() -> float:
    return time.time()


def _clean(text: Any, limit: int = 600) -> str:
    t = re.sub(r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]", " ", str(text or ""))
    t = re.sub(r"\s+", " ", t).strip()
    return t[:limit]


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9 ]+", " ", (text or "").lower()).strip()


def _tokens(text: str) -> set[str]:
    return {w for w in _norm(text).split() if len(w) >= 3 and w not in _STOP}


# ---------------------------------------------------------------------------
# Turns
# ---------------------------------------------------------------------------
def log_turn(role: str, text: str, source: str = "chat", page: str = "", model: str = "") -> None:
    t = _clean(text, 6000)
    if not t:
        return
    try:
        with _db() as c:
            c.execute(
                "INSERT INTO turns(ts, role, text, source, page, model) VALUES(?,?,?,?,?,?)",
                (_now(), role, t, source or "chat", page or "", model or ""),
            )
    except Exception:
        pass


def recent_turns(limit: int = 12) -> list[dict]:
    try:
        with _db() as c:
            rows = c.execute(
                "SELECT ts, role, text, source FROM turns ORDER BY id DESC LIMIT ?", (int(limit),)
            ).fetchall()
        return [dict(r) for r in reversed(rows)]
    except Exception:
        return []


def turns_before(ts: float, limit: int = 8) -> list[dict]:
    try:
        with _db() as c:
            rows = c.execute(
                "SELECT ts, role, text, source FROM turns WHERE ts < ? ORDER BY id DESC LIMIT ?",
                (float(ts), int(limit)),
            ).fetchall()
        return [dict(r) for r in reversed(rows)]
    except Exception:
        return []


def count_turns() -> int:
    try:
        with _db() as c:
            return int(c.execute("SELECT COUNT(*) FROM turns").fetchone()[0])
    except Exception:
        return 0


# ---------------------------------------------------------------------------
# Memories
# ---------------------------------------------------------------------------
def add_memory(text: str, kind: str = "fact", importance: int = 3) -> int | None:
    t = _clean(text, 500)
    if len(t) < 4:
        return None
    kind = kind if kind in _KINDS else "fact"
    try:
        importance = max(1, min(5, int(importance)))
    except Exception:
        importance = 3
    now = _now()
    nt = _norm(t)
    try:
        with _db() as c:
            rows = c.execute(
                "SELECT id, text FROM memories WHERE active=1 AND kind=?", (kind,)
            ).fetchall()
            best_id, best_ratio = None, 0.0
            for r in rows:
                ratio = difflib.SequenceMatcher(None, nt, _norm(r["text"])).ratio()
                if ratio > best_ratio:
                    best_id, best_ratio = int(r["id"]), ratio
            if best_id is not None and best_ratio >= 0.78:
                # Newest statement wins (this is how corrections update memory).
                c.execute(
                    "UPDATE memories SET text=?, importance=MAX(importance,?), updated=?, active=1 WHERE id=?",
                    (t, importance, now, best_id),
                )
                return best_id
            cur = c.execute(
                "INSERT INTO memories(kind, text, importance, created, updated) VALUES(?,?,?,?,?)",
                (kind, t, importance, now, now),
            )
            new_id = int(cur.lastrowid)
            # Cap memory store: drop lowest importance / oldest inactive first.
            total = int(c.execute("SELECT COUNT(*) FROM memories WHERE active=1").fetchone()[0])
            if total > _MAX_MEMORIES:
                extra = total - _MAX_MEMORIES
                c.execute(
                    "UPDATE memories SET active=0 WHERE id IN ("
                    "SELECT id FROM memories WHERE active=1 ORDER BY importance ASC, updated ASC LIMIT ?)",
                    (extra,),
                )
            return new_id
    except Exception:
        return None


def list_memories(kind: str | None = None, limit: int = 300) -> list[dict]:
    try:
        with _db() as c:
            if kind:
                rows = c.execute(
                    "SELECT * FROM memories WHERE active=1 AND kind=? ORDER BY updated DESC LIMIT ?",
                    (kind, int(limit)),
                ).fetchall()
            else:
                rows = c.execute(
                    "SELECT * FROM memories WHERE active=1 ORDER BY updated DESC LIMIT ?", (int(limit),)
                ).fetchall()
        return [dict(r) for r in rows]
    except Exception:
        return []


def delete_memory(mid: int) -> None:
    try:
        with _db() as c:
            c.execute("UPDATE memories SET active=0 WHERE id=?", (int(mid),))
    except Exception:
        pass


def forget_matching(query: str) -> int:
    """Deactivate memories that overlap the query. Used by 'forget that...' and corrections."""
    toks = _tokens(query)
    if not toks:
        return 0
    count = 0
    try:
        with _db() as c:
            rows = c.execute("SELECT id, text FROM memories WHERE active=1").fetchall()
            for r in rows:
                mt = _tokens(r["text"])
                if not mt:
                    continue
                overlap = len(toks & mt) / max(1, len(toks))
                if overlap >= 0.55 or _norm(query) in _norm(r["text"]):
                    c.execute("UPDATE memories SET active=0 WHERE id=?", (int(r["id"]),))
                    count += 1
    except Exception:
        pass
    return count


def clear_memories() -> None:
    try:
        with _db() as c:
            c.execute("UPDATE memories SET active=0")
            c.execute("DELETE FROM summaries")
    except Exception:
        pass


def wipe_all() -> None:
    """Full local wipe: turns, memories, summaries, media files."""
    try:
        with _db() as c:
            c.execute("DELETE FROM turns")
            c.execute("DELETE FROM memories")
            c.execute("DELETE FROM summaries")
            c.execute("DELETE FROM media")
    except Exception:
        pass
    for folder in (MEDIA_VOICE, MEDIA_SNAPSHOTS):
        try:
            for p in folder.glob("*"):
                if p.is_file():
                    p.unlink(missing_ok=True)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Retrieval
# ---------------------------------------------------------------------------
def retrieve_memories(query: str = "", k: int = 8) -> list[dict]:
    try:
        with _db() as c:
            rows = c.execute(
                "SELECT * FROM memories WHERE active=1 ORDER BY updated DESC LIMIT 500"
            ).fetchall()
    except Exception:
        return []
    if not rows:
        return []
    toks = _tokens(query)
    now = _now()
    scored: list[tuple[float, sqlite3.Row]] = []
    for r in rows:
        mt = _tokens(r["text"])
        overlap = (len(toks & mt) / max(1, len(toks))) if toks else 0.0
        if toks and overlap <= 0:
            continue
        age_days = max(0.0, (now - float(r["updated"] or now)) / 86400.0)
        recency = max(0.0, 1.0 - age_days / 120.0)
        score = overlap * 6.0 + float(r["importance"]) * 0.8 + recency * 1.6
        scored.append((score, r))
    if not scored:
        scored = [(float(r["importance"]) * 1.0, r) for r in rows[:k]]
    scored.sort(key=lambda x: x[0], reverse=True)
    picked = [r for _, r in scored[:k]]
    try:
        with _db() as c:
            for r in picked:
                c.execute(
                    "UPDATE memories SET last_used=?, uses=uses+1 WHERE id=?",
                    (now, int(r["id"])),
                )
    except Exception:
        pass
    return [dict(r) for r in picked]


def latest_summaries(limit: int = 2) -> list[dict]:
    try:
        with _db() as c:
            rows = c.execute(
                "SELECT day, text FROM summaries ORDER BY created DESC LIMIT ?", (int(limit),)
            ).fetchall()
        return [dict(r) for r in rows]
    except Exception:
        return []


def get_memory_context(query: str = "", max_items: int = 8, max_chars: int = 1500) -> str:
    bits: list[str] = []
    mems = retrieve_memories(query, max_items)
    if mems:
        bits.append("Long-term memory (auto-learned):")
        for m in mems:
            bits.append(f"- [{m.get('kind', 'fact')}] {m.get('text', '')}")
    sums = latest_summaries(2)
    if sums:
        bits.append("Recent day summaries:")
        for s in sums:
            bits.append(f"- {s.get('day', '')}: {s.get('text', '')[:420]}")
    if not bits:
        return ""
    out = "\n".join(bits)
    return out[:max_chars]


def previous_session_context(session_start_ts: float, limit: int = 8) -> str:
    turns = turns_before(session_start_ts, limit)
    if not turns:
        return ""
    lines = []
    for t in turns:
        role = "User" if t.get("role") == "user" else "JARVIS"
        text = _clean(t.get("text", ""), 240)
        if text:
            lines.append(f"{role}: {text}")
    if not lines:
        return ""
    return "Previous conversation (most recent first):\n" + "\n".join(lines)[-1200:]


# ---------------------------------------------------------------------------
# LLM extraction / reflection
# ---------------------------------------------------------------------------
def _json_array(raw: str) -> list[dict]:
    if not raw:
        return []
    m = re.search(r"\[.*\]", raw, re.DOTALL)
    if not m:
        return []
    try:
        data = json.loads(m.group(0))
        return [x for x in data if isinstance(x, dict)]
    except Exception:
        # last-resort: parse individual objects
        out = []
        for obj in re.findall(r"\{[^{}]*\}", m.group(0)):
            try:
                d = json.loads(obj)
                if isinstance(d, dict):
                    out.append(d)
            except Exception:
                pass
        return out


def _llm(api_key: str, model: str, messages: list[dict], max_tokens: int = 500, timeout: int = 20) -> str:
    if not api_key:
        return ""
    models = [model]
    for fallback in ("google/gemma-4-31b-it", "recursive/flint-v1.0:free"):
        if fallback not in models:
            models.append(fallback)
    for m in models:
        try:
            r = requests_post(api_key, m, messages, max_tokens, timeout)
            if r.status_code != 200:
                continue
            txt = (r.json().get("choices", [{}])[0].get("message", {}).get("content", "") or "").strip()
            if txt:
                return txt
        except Exception:
            continue
    return ""


def requests_post(api_key: str, model: str, messages: list[dict], max_tokens: int, timeout: int):
    import requests

    return requests.post(
        API_URL,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "http://localhost",
            "X-Title": "JARVIS Memory",
        },
        json={"model": model, "messages": messages, "temperature": 0.1, "max_tokens": max_tokens},
        timeout=timeout,
    )


def _turns_text(turns: Iterable[dict]) -> str:
    lines = []
    for t in turns:
        role = "User" if t.get("role") == "user" else "JARVIS"
        txt = _clean(t.get("text", ""), 1200)
        if txt:
            lines.append(f"{role}: {txt}")
    return "\n".join(lines)[-8000:]


_EXTRACT_PROMPT = """You are JARVIS's memory subsystem. Extract durable facts about the USER worth remembering in future sessions.

Include: identity (name, age, location), preferences (likes/dislikes/tone), goals, projects, routines, relationships, important dates, recurring tasks, and surroundings/context the user explicitly mentions.

Rules:
- Only facts explicitly stated or strongly implied BY THE USER. Never invent.
- Ignore greetings, one-off questions, weather, media playback, and claims made only by the assistant.
- Write each fact as a self-contained sentence about the user ("The user's name is Ram", "The user is learning Python").
- kind must be one of: identity, preference, goal, project, routine, person, date, fact, surrounding.
- importance is 1-5 (5 = core identity, 1 = minor detail).
- If there is nothing durable, return [].

Return ONLY a JSON array:
[{"kind":"preference","text":"...","importance":3}]
"""

_CORRECT_PROMPT = """The user corrected JARVIS. Read the previous reply and the user's correction.
Extract the corrected durable facts about the user, and a short phrase that identifies the WRONG old memory to forget.

Return ONLY JSON:
{"facts":[{"kind":"identity|preference|goal|project|routine|person|date|fact|surrounding","text":"...","importance":3}],"forget_query":"short phrase or empty"}
"""


def learn_from_text(api_key: str, model: str, turns_text: str, gen: int | None = None) -> list[dict]:
    if not api_key or not turns_text.strip():
        return []
    raw = _llm(
        api_key,
        model,
        [
            {"role": "system", "content": _EXTRACT_PROMPT},
            {"role": "user", "content": turns_text},
        ],
        max_tokens=600,
        timeout=20,
    )
    items = _json_array(raw)
    stored = []
    for it in items[:20]:
        # A correction may have landed while this extraction was in flight.
        # Discard stale results so old facts can't overwrite newer corrections.
        if gen is not None and gen != _LEARN_GEN:
            return stored
        text = _clean(it.get("text", ""), 400)
        if len(text) < 4:
            continue
        kind = str(it.get("kind", "fact")).lower()
        imp = it.get("importance", 3)
        try:
            imp = int(imp)
        except Exception:
            imp = 3
        add_memory(text, kind, imp)
        stored.append({"kind": kind, "text": text, "importance": imp})
    return stored


def learn_correction(api_key: str, model: str, prev_reply: str, correction: str) -> list[dict]:
    if not api_key:
        return []
    bump_learning_epoch()
    raw = _llm(
        api_key,
        model,
        [
            {"role": "system", "content": _CORRECT_PROMPT},
            {
                "role": "user",
                "content": f"Previous reply:\n{_clean(prev_reply, 1200)}\n\nUser correction:\n{_clean(correction, 800)}",
            },
        ],
        max_tokens=500,
        timeout=20,
    )
    data: dict = {}
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if m:
        try:
            data = json.loads(m.group(0))
        except Exception:
            data = {}
    if data.get("forget_query"):
        forget_matching(str(data["forget_query"]))
    facts = data.get("facts") or []
    stored = []
    for it in facts[:10]:
        if not isinstance(it, dict):
            continue
        text = _clean(it.get("text", ""), 400)
        if len(text) < 4:
            continue
        kind = str(it.get("kind", "fact")).lower()
        try:
            imp = int(it.get("importance", 4))
        except Exception:
            imp = 4
        add_memory(text, kind, imp)
        stored.append({"text": text, "kind": kind})
    return stored


def learn_correction_async(api_key: str, model: str, prev_reply: str, correction: str) -> bool:
    if not api_key:
        return False
    if not _LEARN_LOCK.acquire(blocking=False):
        return False

    def worker():
        try:
            learn_correction(api_key, model, prev_reply, correction)
        finally:
            try:
                _LEARN_LOCK.release()
            except Exception:
                pass

    threading.Thread(target=worker, daemon=True).start()
    return True


def _learn_worker(api_key: str, model: str, turns_text: str, gen: int) -> None:
    try:
        learn_from_text(api_key, model, turns_text, gen=gen)
    finally:
        try:
            _LEARN_LOCK.release()
        except Exception:
            pass


def bump_learning_epoch() -> int:
    """Invalidate any in-flight background extraction (used after corrections)."""
    global _LEARN_GEN
    with _GEN_LOCK:
        _LEARN_GEN += 1
        return _LEARN_GEN


def maybe_learn_async(api_key: str, model: str = "google/gemma-4-31b-it", force: bool = False) -> bool:
    """Learn in the background. Trigger words learn immediately; otherwise every ~3 min."""
    if not api_key:
        return False
    turns = recent_turns(14)
    if len(turns) < 2:
        return False
    text = _turns_text(turns)
    trig = bool(re.search(
        r"\b(my name|i am|i'm|i live|i work|i study|i like|i love|i prefer|i hate|"
        r"i'm building|i'm working|i'm learning|remember|my goal|my project|my birthday|"
        r"my friend|my family|every day|every morning|routine)\b",
        text, re.I,
    ))
    last = _meta_get("last_learn_ts", "0")
    try:
        lastf = float(last)
    except Exception:
        lastf = 0.0
    if not force and not trig and (_now() - lastf) < 180:
        return False
    if not _LEARN_LOCK.acquire(blocking=False):
        return False
    gen = _LEARN_GEN
    _meta_set("last_learn_ts", str(_now()))
    th = threading.Thread(target=_learn_worker, args=(api_key, model, text, gen), daemon=True)
    th.start()
    return True


_SUMMARY_PROMPT = """Summarize this conversation for long-term memory in 120 words or less.
Focus on: who the user is, what they are working on, preferences, unresolved tasks, and important personal context.
Write plain text only, no bullets, no preamble."""


def reflect_async(api_key: str, model: str) -> bool:
    """Once per day: summarize recent conversation and store it for future sessions."""
    if not api_key:
        return False
    today = time.strftime("%Y-%m-%d")
    if _meta_get("last_reflect_day", "") == today:
        return False
    turns = recent_turns(40)
    if len(turns) < 2:
        return False
    _meta_set("last_reflect_day", today)
    text = _turns_text(turns)

    def worker():
        raw = _llm(
            api_key,
            model,
            [
                {"role": "system", "content": _SUMMARY_PROMPT},
                {"role": "user", "content": text},
            ],
            max_tokens=260,
            timeout=25,
        )
        if raw:
            try:
                with _db() as c:
                    c.execute(
                        "INSERT INTO summaries(day, text, created) VALUES(?,?,?) "
                        "ON CONFLICT(day) DO UPDATE SET text=excluded.text, created=excluded.created",
                        (today, _clean(raw, 1200), _now()),
                    )
            except Exception:
                pass

    threading.Thread(target=worker, daemon=True).start()
    return True


# ---------------------------------------------------------------------------
# Local correction heuristics (instant, no LLM)
# ---------------------------------------------------------------------------
def apply_correction_local(text: str) -> str:
    t = (text or "").strip()
    low = t.lower()
    facts: list[tuple[str, str, int]] = []

    def add(kind: str, value: str, imp: int = 4):
        value = _clean(value, 200)
        if len(value) >= 2:
            facts.append((kind, value, imp))

    m = re.search(r"\bmy name is\s+([A-Za-z][A-Za-z .'\-]{1,40}?)(?=\s*(?:[,\.!?]|$|\band\b))", t, re.I)
    if m:
        add("identity", f"The user's name is {m.group(1).strip().rstrip('.')}.", 5)
    m = re.search(r"\bi(?:'m| am)\s+(\d{1,3})\s+years? old\b", t, re.I)
    if m:
        add("identity", f"The user is {m.group(1)} years old.", 5)
    m = re.search(r"\bi live in\s+([A-Za-z][A-Za-z .,'\-]{2,60}?)(?=\s*(?:[,\.!?]|$|\band\b))", t, re.I)
    if m:
        add("identity", f"The user lives in {m.group(1).strip().rstrip('.')}.", 5)
    m = re.search(r"\bi(?:'m| am)\s+(?:working on|building|learning|studying)\s+(.{2,140}?)(?=\s*(?:[,\.!?]|$))", t, re.I)
    if m:
        add("project", f"The user is working on {m.group(1).strip().rstrip('.')}.", 4)
    m = re.search(r"\bi\s+(?:really\s+)?(like|love|prefer|enjoy|hate|dislike)\s+(.{2,140}?)(?=\s*(?:[,\.!?]|$))", t, re.I)
    if m:
        add("preference", f"The user {m.group(1).lower()}s {m.group(2).strip().rstrip('.')}.", 4)
    m = re.search(r"\b(?:remember|note)\s+(?:that\s+)?(.{3,200})", t, re.I)
    if m:
        add("fact", f"The user asked JARVIS to remember: {m.group(1).strip().rstrip('.')}.", 4)

    if not facts and re.match(r"^(?:no|nope|wrong|that'?s wrong|incorrect|actually|i meant)\b", low):
        # Keep a correction as a fact so the corrected answer is remembered.
        cleaned = re.sub(r"^(?:no|nope|wrong|that'?s wrong|incorrect|actually|i meant)[,:\s]*", "", t, flags=re.I).strip()
        if len(cleaned) >= 8:
            add("fact", f"Correction from the user: {cleaned}", 3)

    if not facts:
        return ""
    # New durable facts invalidate background extraction already in flight.
    bump_learning_epoch()
    for kind, value, imp in facts:
        add_memory(value, kind, imp)
    return "; ".join(v for _, v, _ in facts)


# ---------------------------------------------------------------------------
# Media: voice clips + camera snapshots
# ---------------------------------------------------------------------------
def _save_media(kind: str, raw: bytes, suffix: str, description: str = "") -> int | None:
    if not raw:
        return None
    folder = MEDIA_VOICE if kind == "voice" else MEDIA_SNAPSHOTS
    folder.mkdir(parents=True, exist_ok=True)
    name = f"{kind}_{int(_now() * 1000)}_{uuid.uuid4().hex[:6]}{suffix}"
    path = folder / name
    try:
        path.write_bytes(raw)
    except Exception:
        return None
    try:
        with _db() as c:
            cur = c.execute(
                "INSERT INTO media(kind, path, description, created) VALUES(?,?,?,?)",
                (kind, str(path), _clean(description, 2000), _now()),
            )
            mid = int(cur.lastrowid)
            total = int(c.execute("SELECT COUNT(*) FROM media WHERE kind=?", (kind,)).fetchone()[0])
            if total > _MAX_MEDIA_PER_KIND:
                for row in c.execute(
                    "SELECT id, path FROM media WHERE kind=? ORDER BY created ASC LIMIT ?",
                    (kind, total - _MAX_MEDIA_PER_KIND),
                ).fetchall():
                    try:
                        Path(row["path"]).unlink(missing_ok=True)
                    except Exception:
                        pass
                    c.execute("DELETE FROM media WHERE id=?", (int(row["id"]),))
            return mid
    except Exception:
        return None


def save_voice_clip(raw: bytes, transcript: str = "") -> int | None:
    return _save_media("voice", raw, ".wav", transcript)


def save_snapshot(raw: bytes, description: str = "") -> int | None:
    return _save_media("snapshot", raw, ".jpg", description)


def update_latest_snapshot_description(text: str) -> None:
    try:
        with _db() as c:
            row = c.execute(
                "SELECT id FROM media WHERE kind='snapshot' AND created > ? ORDER BY created DESC LIMIT 1",
                (_now() - 900,),
            ).fetchone()
            if row:
                c.execute(
                    "UPDATE media SET description=? WHERE id=?",
                    (_clean(text, 2000), int(row["id"])),
                )
    except Exception:
        pass


def list_media(kind: str, limit: int = 60) -> list[dict]:
    try:
        with _db() as c:
            rows = c.execute(
                "SELECT * FROM media WHERE kind=? ORDER BY created DESC LIMIT ?",
                (kind, int(limit)),
            ).fetchall()
        return [dict(r) for r in rows]
    except Exception:
        return []


def delete_media(mid: int) -> None:
    try:
        with _db() as c:
            row = c.execute("SELECT path FROM media WHERE id=?", (int(mid),)).fetchone()
            if row:
                try:
                    Path(row["path"]).unlink(missing_ok=True)
                except Exception:
                    pass
            c.execute("DELETE FROM media WHERE id=?", (int(mid),))
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Stats / meta
# ---------------------------------------------------------------------------
def _meta_get(key: str, default: str = "") -> str:
    try:
        with _db() as c:
            row = c.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return str(row["value"]) if row else default
    except Exception:
        return default


def _meta_set(key: str, value: str) -> None:
    try:
        with _db() as c:
            c.execute(
                "INSERT INTO meta(key, value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, str(value)),
            )
    except Exception:
        pass


def get_meta(key: str, default: str = "") -> str:
    return _meta_get(key, default)


def set_meta(key: str, value: str) -> None:
    _meta_set(key, value)


def memory_stats() -> dict:
    out = {"turns": 0, "memories": 0, "summaries": 0, "voice": 0, "snapshots": 0, "media_mb": 0.0}
    try:
        with _db() as c:
            out["turns"] = int(c.execute("SELECT COUNT(*) FROM turns").fetchone()[0])
            out["memories"] = int(c.execute("SELECT COUNT(*) FROM memories WHERE active=1").fetchone()[0])
            out["summaries"] = int(c.execute("SELECT COUNT(*) FROM summaries").fetchone()[0])
            out["voice"] = int(c.execute("SELECT COUNT(*) FROM media WHERE kind='voice'").fetchone()[0])
            out["snapshots"] = int(c.execute("SELECT COUNT(*) FROM media WHERE kind='snapshot'").fetchone()[0])
    except Exception:
        pass
    try:
        size = sum(p.stat().st_size for p in MEDIA_DIR.rglob("*") if p.is_file())
        out["media_mb"] = round(size / (1024 * 1024), 2)
    except Exception:
        pass
    return out
