from __future__ import annotations

import base64
import json
import logging
from typing import Any, Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from ..deps import get_provider
from ..prompts import vision_prompt
from ..providers import AIProvider, ChatMessage, ProviderError
from ..security import require_device

log = logging.getLogger("jarvis.vision")
router = APIRouter(tags=["vision"], dependencies=[Depends(require_device)])

ALLOWED_MIME = {"image/jpeg", "image/png", "image/webp", "image/gif"}
MAX_BYTES = 12 * 1024 * 1024


@router.post("/v1/vision/analyze")
async def analyze(
    image: UploadFile = File(...),
    mode: Literal["identify", "text", "translate", "solve", "describe"] = Form("identify"),
    question: str = Form(""),
    provider: AIProvider = Depends(get_provider),
) -> dict:
    if provider.name == "unconfigured":
        raise HTTPException(status_code=503, detail="AI provider is not configured on the server")
    mime = (image.content_type or "").lower()
    if mime not in ALLOWED_MIME:
        raise HTTPException(status_code=415, detail="Use JPEG, PNG, WebP, or GIF")
    raw = await image.read()
    if not raw:
        raise HTTPException(status_code=400, detail="Empty image")
    if len(raw) > MAX_BYTES:
        raise HTTPException(status_code=413, detail="Image is larger than 12 MB")

    b64 = base64.b64encode(raw).decode("ascii")
    message = ChatMessage(
        role="user",
        content=[
            {"type": "text", "text": vision_prompt(mode, question)},
            {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
        ],
    )
    try:
        text = await provider.complete([message], thinking=False, json_mode=True, max_tokens=1400)
    except ProviderError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    parsed = _parse(text)
    if _is_empty(parsed):
        # Some models occasionally answer with an empty JSON object. Ask once
        # more in plain text instead of returning a blank result to the phone.
        log.info("vision: empty JSON result, retrying in plain text")
        try:
            fallback = await provider.complete([message], thinking=False, json_mode=False, max_tokens=700)
        except ProviderError as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
        if fallback.strip():
            parsed = {"description": fallback.strip(), "objects": [], "text": "", "translation": "", "answer": "", "safety": "ok"}
    if _is_empty(parsed):
        log.warning("vision: provider returned no usable content")
        raise HTTPException(status_code=502, detail="The vision model returned no usable description. Try again.")
    return {
        "mode": mode,
        "result": parsed,
        "provider": provider.name,
        "model": provider.model,
        "note": "Confidence values are shown only when the model returns them; this app never invents them.",
    }


def _parse(text: str) -> dict:
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        return {"description": text.strip(), "objects": [], "text": "", "translation": "", "answer": "", "safety": "ok"}
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        return {"description": value.strip(), "objects": [], "text": "", "translation": "", "answer": "", "safety": "ok"}
    return {"description": text.strip(), "objects": [], "text": "", "translation": "", "answer": "", "safety": "ok"}


def _is_empty(parsed: dict) -> bool:
    for key in ("description", "text", "translation", "answer"):
        value = parsed.get(key)
        if isinstance(value, str) and value.strip():
            return False
    objects = parsed.get("objects")
    return not (isinstance(objects, list) and len(objects) > 0)
