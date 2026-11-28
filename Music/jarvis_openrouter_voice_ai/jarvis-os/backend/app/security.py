from __future__ import annotations

import hmac
import time
from collections import defaultdict, deque
from typing import Deque

from fastapi import Depends, Header, HTTPException, Request

from .config import Settings, get_settings


def _extract_bearer(authorization: str | None) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")
    return authorization[7:].strip()


async def require_device(
    authorization: str | None = Header(default=None),
    settings: Settings = Depends(get_settings),
) -> str:
    token = _extract_bearer(authorization)
    if not hmac.compare_digest(token, settings.device_token):
        raise HTTPException(status_code=401, detail="Invalid device token")
    return token


class SlidingWindowLimiter:
    """Small in-process limiter for a single-user local backend.

    For multi-user deployments, replace this with a Redis-backed limiter.
    """

    def __init__(self, limit: int, window_seconds: float = 60.0) -> None:
        self.limit = max(1, limit)
        self.window = window_seconds
        self._hits: dict[str, Deque[float]] = defaultdict(deque)

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        q = self._hits[key]
        while q and now - q[0] > self.window:
            q.popleft()
        if len(q) >= self.limit:
            return False
        q.append(now)
        return True


tts_limiter = SlidingWindowLimiter(limit=get_settings().tts_rate_limit_per_minute)


def check_tts_limit(request: Request) -> None:
    key = request.client.host if request.client else "local"
    if not tts_limiter.allow(key):
        raise HTTPException(status_code=429, detail="Too many speech requests; try again shortly")
