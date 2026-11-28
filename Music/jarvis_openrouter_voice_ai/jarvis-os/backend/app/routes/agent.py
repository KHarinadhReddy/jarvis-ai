from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..deps import get_provider
from ..prompts import AGENT_SYSTEM
from ..providers import AIProvider, ChatMessage, ProviderError
from ..security import require_device

log = logging.getLogger("jarvis.agent")
router = APIRouter(tags=["agent"], dependencies=[Depends(require_device)])


class AgentRequest(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    context: str = ""
    tools: list[dict[str, Any]] = Field(default_factory=list, max_length=40)


@router.post("/v1/agent/plan")
async def plan(request: AgentRequest, provider: AIProvider = Depends(get_provider)) -> dict:
    if provider.name == "unconfigured":
        raise HTTPException(status_code=503, detail="AI provider is not configured on the server")
    user = (
        f"Request: {request.text}\n"
        f"Context: {request.context[:6000]}\n"
        f"Available tools: {json.dumps(request.tools, ensure_ascii=False)[:6000]}\n"
        "Return only the JSON plan."
    )
    try:
        text = await provider.complete(
            [ChatMessage(role="system", content=AGENT_SYSTEM), ChatMessage(role="user", content=user)],
            thinking=True,
            json_mode=True,
            max_tokens=1800,
        )
    except ProviderError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        parsed = {"summary": text, "steps": []}
    return {
        "plan": parsed,
        "provider": provider.name,
        "note": "The server proposes a plan only. The Android app validates and executes approved device tools.",
    }
