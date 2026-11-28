from __future__ import annotations

from app.speech import (
    detect_language,
    normalize_for_speech,
    plan_speech,
    split_sentences,
    voice_for,
)


def test_normalization_removes_markdown_and_expands_units():
    value = normalize_for_speech("## Status\n**Battery:** 87% and 24°C. Visit https://example.com")
    assert "#" not in value
    assert "**" not in value
    assert "87 percent" in value
    assert "24 degrees Celsius" in value
    assert "https" not in value


def test_split_sentences_keeps_punctuation():
    assert split_sentences("One. Two? Three!") == ["One.", "Two?", "Three!"]


def test_detect_language_telugu():
    assert detect_language("నమస్కారం, how are you?") == "te-IN"
    assert detect_language("Good morning, sir.") == "en-IN"


def test_voice_selection():
    assert voice_for("te-IN", "male") == "te-IN-MohanNeural"
    assert voice_for("te-IN", "female") == "te-IN-ShrutiNeural"
    assert voice_for("en-IN", "male") == "en-IN-PrabhatNeural"


def test_pauses_vary_and_breaths_are_not_every_sentence():
    text = (
        "Good morning. Your first class starts in one hour. "
        "I have prepared a short plan for the day. Shall I read it out? "
        "It includes study time, a break, and your evening workout. "
        "Let me know if you want to change anything."
    )
    segments = plan_speech(text, language="en-IN")
    assert len(segments) >= 4
    assert len({s.pause_after_ms for s in segments}) > 1
    assert any(s.breath_after for s in segments)
    assert not all(s.breath_after for s in segments)
    assert len({s.rate for s in segments}) > 1
