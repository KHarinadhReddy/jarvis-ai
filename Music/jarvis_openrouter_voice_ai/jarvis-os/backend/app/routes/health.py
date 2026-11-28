from __future__ import annotations

from fastapi import APIRouter, Depends

from ..config import Settings, get_settings
from ..deps import get_provider
from ..providers import AIProvider

router = APIRouter(tags=["system"])


@router.get("/")
async def root() -> dict:
    return {
        "name": "J.A.R.V.I.S. Backend",
        "version": get_settings().version,
        "docs": "/docs",
        "health": "/v1/health",
    }


@router.get("/v1/health")
async def health(
    provider: AIProvider = Depends(get_provider),
    settings: Settings = Depends(get_settings),
) -> dict:
    return {
        "status": "online",
        "version": settings.version,
        "provider": provider.name,
        "model": provider.model,
        "vision": provider.name in {"deepseek", "openrouter", "mock"},
        "tts": "edge-neural",
        "telugu_tts": True,
        "configured": provider.name != "unconfigured",
    }


@router.get("/v1/models")
async def models(
    provider: AIProvider = Depends(get_provider),
    settings: Settings = Depends(get_settings),
) -> dict:
    return {
        "provider": provider.name,
        "default": provider.model,
        "deepseek": settings.deepseek_model,
        "openrouter": settings.openrouter_model,
        "note": "Model selection is configured on the server; the app never holds an AI key.",
    }
