from __future__ import annotations

import asyncio
import hashlib
import random
import re
from dataclasses import asdict, dataclass
from typing import Iterable

import edge_tts

from .config import get_settings


class SpeechError(RuntimeError):
    pass


VOICE_OPTIONS: dict[str, dict[str, str]] = {
    "en-IN": {"female": "en-IN-NeerjaNeural", "male": "en-IN-PrabhatNeural"},
    "en-US": {"female": "en-US-EmmaNeural", "male": "en-US-BrianNeural"},
    "en-GB": {"female": "en-GB-SoniaNeural", "male": "en-GB-RyanNeural"},
    "te-IN": {"female": "te-IN-ShrutiNeural", "male": "te-IN-MohanNeural"},
    "hi-IN": {"female": "hi-IN-SwaraNeural", "male": "hi-IN-MadhurNeural"},
    "kn-IN": {"female": "kn-IN-SapnaNeural", "male": "kn-IN-GaganNeural"},
    "ta-IN": {"female": "ta-IN-PallaviNeural", "male": "ta-IN-ValluvarNeural"},
    "ml-IN": {"female": "ml-IN-SobhanaNeural", "male": "ml-IN-MidhunNeural"},
    "mr-IN": {"female": "mr-IN-AarohiNeural", "male": "mr-IN-ManoharNeural"},
    "bn-IN": {"female": "bn-IN-TanishaaNeural", "male": "bn-IN-BashkarNeural"},
    "gu-IN": {"female": "gu-IN-DhwaniNeural", "male": "gu-IN-NiranjanNeural"},
}

INDIC_LANGS = {"te", "hi", "kn", "ta", "ml", "mr", "bn", "gu"}


def _lang_base(language: str) -> str:
    return (language or "en-IN").strip().replace("_", "-").split("-")[0].lower()


def is_indic(language: str) -> bool:
    return _lang_base(language) in INDIC_LANGS


def detect_language(text: str, fallback: str = "en-IN") -> str:
    """Detect the dominant script. This is intentionally simple and deterministic."""
    telugu = sum(1 for ch in text if "\u0c00" <= ch <= "\u0c7f")
    latin = sum(1 for ch in text if ch.isascii() and ch.isalpha())
    if telugu >= 4 and telugu >= max(2, latin // 3):
        return "te-IN"
    if latin > 0:
        return fallback if _lang_base(fallback) == "en" else "en-IN"
    return fallback


def voice_for(
    language: str,
    gender: str = "male",
    requested: str | None = None,
) -> str:
    settings = get_settings()
    if requested and requested in _all_voice_ids():
        return requested
    lang = (language or "en-IN").strip().replace("_", "-")
    table = VOICE_OPTIONS.get(lang)
    if not table:
        base = _lang_base(lang)
        table = next((v for k, v in VOICE_OPTIONS.items() if _lang_base(k) == base), None)
    if table:
        return table.get("female" if gender == "female" else "male", table["male"])
    return settings.tts_voice_en


def _all_voice_ids() -> set[str]:
    return {v for table in VOICE_OPTIONS.values() for v in table.values()} | {
        get_settings().tts_voice_en,
        get_settings().tts_voice_te,
    }


def normalize_for_speech(text: str, limit: int = 1200) -> str:
    """Remove page formatting and expand common symbols so TTS reads naturally."""
    value = text or ""
    value = re.sub(r"```.*?```", " ", value, flags=re.DOTALL)
    value = re.sub(r"`([^`]*)`", r"\1", value)
    value = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", value)
    value = re.sub(r"https?://\S+", " link ", value)
    value = re.sub(r"<[^>]+>", " ", value)
    value = re.sub(r"^\s*[#>*\-•]+\s*", "", value, flags=re.MULTILINE)
    value = re.sub(r"[*_~|]+", "", value)
    value = re.sub(r"[\U0001F300-\U0001FAFF\u2600-\u27BF]", "", value)
    value = re.sub(r"\be\.g\.\b", "for example", value, flags=re.IGNORECASE)
    value = re.sub(r"\bi\.e\.\b", "that is", value, flags=re.IGNORECASE)
    value = re.sub(r"\betc\.\b", "etcetera", value, flags=re.IGNORECASE)
    value = re.sub(r"₹\s?([\d,]+)", r"\1 rupees", value)
    value = re.sub(r"\$\s?([\d,.]+)", r"\1 dollars", value)
    value = re.sub(r"(\d)\s*°C", r"\1 degrees Celsius", value)
    value = re.sub(r"(\d)\s*°F", r"\1 degrees Fahrenheit", value)
    value = value.replace("%", " percent ").replace("&", " and ")
    value = re.sub(r"\s+", " ", value).strip()
    if not value:
        return ""
    if len(value) > limit:
        cut = value[:limit]
        boundary = max(cut.rfind(". "), cut.rfind("? "), cut.rfind("! "))
        value = (cut[:boundary + 1] if boundary > limit * 0.6 else cut).strip()
    if value and value[-1] not in ".!?।":
        value += "."
    return value


def split_sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?।])\s+|\n+", text.strip())
    return [p.strip() for p in parts if p.strip()]


@dataclass
class SpeechSegment:
    text: str
    voice: str
    rate: str
    pitch: str
    pause_after_ms: int
    breath_after: bool

    def to_dict(self) -> dict:
        return asdict(self)


def _jitter_percent(value: int, amount: int, rng: random.Random) -> str:
    number = value + rng.randint(-amount, amount)
    return f"{number:+d}%"


def _jitter_hz(value: int, amount: int, rng: random.Random) -> str:
    number = value + rng.randint(-amount, amount)
    return f"{number:+d}Hz"


def plan_speech(
    text: str,
    *,
    language: str = "en-IN",
    voice: str | None = None,
    gender: str = "male",
    rate: str | None = None,
    pitch: str | None = None,
) -> list[SpeechSegment]:
    normalized = normalize_for_speech(text)
    if not normalized:
        return []
    sentences = split_sentences(normalized)
    if not sentences:
        return []
    seed = int(hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16], 16)
    rng = random.Random(seed)
    base_rate = 0
    if rate:
        match = re.match(r"([+-]?\d+)", rate)
        if match:
            base_rate = int(match.group(1))
    elif is_indic(language):
        base_rate = -10
    else:
        base_rate = -6
    base_pitch = 0
    if pitch:
        match = re.match(r"([+-]?\d+)", pitch)
        if match:
            base_pitch = int(match.group(1))

    segments: list[SpeechSegment] = []
    for index, sentence in enumerate(sentences):
        segment_lang = detect_language(sentence, fallback=language)
        segment_voice = voice or voice_for(segment_lang, gender)
        if voice:
            segment_voice = voice
        if sentence.endswith(("?", "!")):
            pause = rng.randint(300, 520)
        elif sentence.endswith((",", ";", ":")):
            pause = rng.randint(110, 210)
        else:
            pause = rng.randint(260, 470)
        if len(sentence) > 140:
            pause += rng.randint(40, 110)
        breath = index < len(sentences) - 1 and rng.random() < 0.32
        segments.append(
            SpeechSegment(
                text=sentence,
                voice=segment_voice,
                rate=_jitter_percent(base_rate, 2, rng),
                pitch=_jitter_hz(base_pitch, 2, rng),
                pause_after_ms=pause,
                breath_after=breath,
            )
        )
    return segments


async def synthesize_edge(
    text: str,
    *,
    voice: str,
    rate: str = "+0%",
    pitch: str = "+0Hz",
    timeout_seconds: float = 25.0,
) -> bytes:
    """Generate MP3 bytes with Edge neural TTS. No SSML tags are sent."""
    if not text.strip():
        return b""

    async def _once(v: str) -> bytes:
        communicate = edge_tts.Communicate(text=text, voice=v, rate=rate, pitch=pitch)
        audio = bytearray()
        async for chunk in communicate.stream():
            if chunk.get("type") == "audio" and chunk.get("data"):
                audio.extend(chunk["data"])
        return bytes(audio)

    try:
        data = await asyncio.wait_for(_once(voice), timeout=timeout_seconds)
        if data:
            return data
    except Exception:
        pass
    # A voice can intermittently return no audio. Retry once with the other
    # native voice for the same language before giving up.
    fallback = _fallback_voice(voice)
    if fallback and fallback != voice:
        try:
            data = await asyncio.wait_for(_once(fallback), timeout=timeout_seconds)
            if data:
                return data
        except Exception:
            pass
    raise SpeechError("Speech synthesis failed; check the backend network and Edge TTS availability")


def _fallback_voice(voice: str) -> str:
    for table in VOICE_OPTIONS.values():
        if voice in table.values():
            return table["female"] if voice == table["male"] else table["male"]
    return get_settings().tts_voice_en


def voice_list() -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for locale, table in VOICE_OPTIONS.items():
        for gender, voice in table.items():
            rows.append({"locale": locale, "gender": gender, "voice": voice})
    return rows
