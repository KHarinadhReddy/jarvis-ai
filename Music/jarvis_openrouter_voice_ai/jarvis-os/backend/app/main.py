from __future__ import annotations

import logging
import time
import uuid

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .config import get_settings
from .providers import ProviderError
from .routes import agent, chat, health, speech, vision

settings = get_settings()
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
log = logging.getLogger("jarvis")

app = FastAPI(
    title=settings.app_name,
    version=settings.version,
    description="Authenticated AI, vision, speech, and planning backend for J.A.R.V.I.S. Mobile.",
)

if settings.origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.origins,
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Authorization", "Content-Type"],
    )


@app.middleware("http")
async def request_context(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex
    request.state.request_id = request_id
    started = time.perf_counter()
    response = await call_next(request)
    elapsed = (time.perf_counter() - started) * 1000
    response.headers["X-Request-ID"] = request_id
    log.info(
        "%s %s %s %.1fms",
        request.method,
        request.url.path,
        response.status_code,
        elapsed,
    )
    return response


@app.exception_handler(ProviderError)
async def provider_error_handler(request: Request, exc: ProviderError):
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": str(exc), "request_id": getattr(request.state, "request_id", "")},
    )


app.include_router(health.router)
app.include_router(chat.router)
app.include_router(vision.router)
app.include_router(speech.router)
app.include_router(agent.router)


@app.on_event("startup")
async def startup() -> None:
    log.info("J.A.R.V.I.S. backend %s online (provider=%s)", settings.version, settings.provider_name)
    if settings.provider_name == "unconfigured":
        log.warning("No AI key configured; chat and vision will return 503. TTS still works.")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=False)
