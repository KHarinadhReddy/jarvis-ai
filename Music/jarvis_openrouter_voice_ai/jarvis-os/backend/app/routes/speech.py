from __future__ import annotations

import base64
import logging
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field

from ..security import check_tts_limit, require_device
from ..speech import (
    SpeechError,
    detect_language,
    normalize_for_speech,
    plan_speech,
    synthesize_edge,
    voice_for,
    voice_list,
)

log = logging.getLogger("jarvis.speech")
router = APIRouter(tags=["speech"], dependencies=[Depends(require_device)])


class TtsRequest(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    language: str | None = None
    voice: str | None = None
    gender: Literal["male", "female"] = "male"
    rate: str | None = None
    pitch: str | None = None


@router.get("/v1/tts/voices")
async def voices() -> dict:
    return {"voices": voice_list()}


@router.post("/v1/tts/plan")
async def plan(request: TtsRequest) -> dict:
    normalized = normalize_for_speech(request.text)
    if not normalized:
        raise HTTPException(status_code=400, detail="No readable text")
    language = request.language or detect_language(normalized)
    segments = plan_speech(
        normalized,
        language=language,
        voice=request.voice,
        gender=request.gender,
        rate=request.rate,
        pitch=request.pitch,
    )
    return {
        "language": language,
        "normalized": normalized,
        "segments": [s.to_dict() for s in segments],
        "note": "Pauses and breaths are scheduled by the client; confidence is never invented.",
    }


@router.post("/v1/tts/segments")
async def tts_segments(
    request: TtsRequest,
    _: None = Depends(check_tts_limit),
) -> dict:
    """Return one MP3 per sentence plus its pause/breath plan.

    The Android client schedules real silence and breath sounds between these
    clips, so the human-like pacing survives the trip over HTTP.
    """
    normalized = normalize_for_speech(request.text)
    if not normalized:
        raise HTTPException(status_code=400, detail="No readable text")
    language = request.language or detect_language(normalized)
    voice = voice_for(language, request.gender, request.voice)
    segments = plan_speech(
        normalized,
        language=language,
        voice=voice,
        gender=request.gender,
        rate=request.rate,
        pitch=request.pitch,
    )[:14]
    if not segments:
        raise HTTPException(status_code=400, detail="No speakable segments")
    clips: list[dict] = []
    try:
        for seg in segments:
            audio = await synthesize_edge(seg.text, voice=seg.voice, rate=seg.rate, pitch=seg.pitch)
            if not audio:
                raise SpeechError("Speech service returned an empty clip")
            clips.append(
                {
                    "text": seg.text,
                    "voice": seg.voice,
                    "audio_b64": base64.b64encode(audio).decode("ascii"),
                    "pause_after_ms": seg.pause_after_ms,
                    "breath_after": seg.breath_after,
                }
            )
    except SpeechError as exc:
        log.warning("Segmented TTS failed: %s", exc)
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {
        "language": language,
        "normalized": normalized,
        "clips": clips,
        "note": "Client plays clips in order and inserts the scheduled pause and optional breath.",
    }


@router.post("/v1/tts")
async def tts(
    request: TtsRequest,
    _: None = Depends(check_tts_limit),
) -> Response:
    normalized = normalize_for_speech(request.text)
    if not normalized:
        raise HTTPException(status_code=400, detail="No readable text")
    language = request.language or detect_language(normalized)
    voice = voice_for(language, request.gender, request.voice)
    segments = plan_speech(
        normalized,
        language=language,
        voice=voice,
        gender=request.gender,
        rate=request.rate,
        pitch=request.pitch,
    )
    if not segments:
        raise HTTPException(status_code=400, detail="No speakable segments")
    try:
        audio = b"".join(
            [await synthesize_edge(seg.text, voice=seg.voice, rate=seg.rate, pitch=seg.pitch) for seg in segments]
        )
    except SpeechError as exc:
        log.warning("TTS failed: %s", exc)
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    if not audio:
        raise HTTPException(status_code=502, detail="Speech service returned no audio")
    return Response(
        content=audio,
        media_type="audio/mpeg",
        headers={
            "Cache-Control": "no-store",
            "X-Voice": segments[0].voice,
            "X-Language": language,
            "X-Segment-Count": str(len(segments)),
            "X-Pause-After-Ms": str(segments[-1].pause_after_ms),
            "X-Breath-After": "1" if segments[-1].breath_after else "0",
        },
    )
