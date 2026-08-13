"""In-process upload rate limiting — Security_and_Privacy_v2.md SS8
("Upload rate limiting per session/IP"), a requirement carried over from
the (unavailable) v1 doc but never actually implemented until this phase
(Phase 10 security audit found `ErrorCode.RATE_LIMITED` defined and wired
into every error-mapping table, but nothing ever raised it).

Deliberately a simple in-memory fixed-window counter keyed by client IP —
no Redis/external dependency, matching this project's established
"MVP in-process, single worker" precedent (Technical_Architecture_v2.md
SS9, reused for Phase 8's background pipeline). Documented limitation
(docs/SECURITY_AUDIT.md): state is per-worker-process, so a multi-worker
or multi-instance deployment needs a shared store (e.g. Redis) for a true
global limit — explicitly out of scope per Security_and_Privacy_v2.md SS9
"Do-Not-Over-Engineer Notes". Also does not resolve `X-Forwarded-For`:
behind a reverse proxy without that configured, every request appears to
come from the proxy's IP, degrading the limit to a single shared bucket —
acceptable for MVP, documented rather than silently assumed away.
"""

from __future__ import annotations

import time
from collections import defaultdict, deque

from fastapi import Depends, Request, status

from app.core.config import Settings, get_settings
from app.core.errors import ApiError
from app.models.enums import ErrorCode


class InMemoryRateLimiter:
    """Fixed-window: at most `max_requests` accepted per `window_seconds`
    per key. Not thread-safe across multiple OS threads/processes — safe
    under FastAPI's default single-event-loop-per-worker model, where every
    request this limiter sees runs cooperatively on the same loop.

    Holds only the per-key hit-timestamp state; the window/count threshold
    is passed in on each call (from `Settings`, which is cheap to
    re-construct per request and never changes at runtime) rather than
    fixed at construction time, so a single long-lived instance can serve
    every request without needing a separate "reconfigure" step.
    """

    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, key: str, *, max_requests: int, window_seconds: float) -> bool:
        now = time.monotonic()
        hits = self._hits[key]
        while hits and now - hits[0] > window_seconds:
            hits.popleft()
        if len(hits) >= max_requests:
            return False
        hits.append(now)
        return True

    def reset(self) -> None:
        """Test-only escape hatch — never called from application code."""
        self._hits.clear()


_upload_limiter = InMemoryRateLimiter()


def _client_key(request: Request) -> str:
    # No X-Forwarded-For trust boundary is configured for this MVP (see
    # module docstring) — request.client.host is the direct peer address,
    # which is the correct source of truth when there is no trusted proxy
    # in front of the app, and a documented, non-silent degradation when
    # there is one.
    return request.client.host if request.client else "unknown"


def enforce_upload_rate_limit(request: Request, settings: Settings = Depends(get_settings)) -> None:
    """FastAPI dependency — raises `ErrorCode.RATE_LIMITED` (429) once a
    client exceeds `settings.upload_rate_limit_max_requests` uploads per
    `settings.upload_rate_limit_window_seconds`.
    """
    allowed = _upload_limiter.allow(
        _client_key(request),
        max_requests=settings.upload_rate_limit_max_requests,
        window_seconds=settings.upload_rate_limit_window_seconds,
    )
    if not allowed:
        raise ApiError(ErrorCode.RATE_LIMITED, status.HTTP_429_TOO_MANY_REQUESTS)


def reset_upload_rate_limiter() -> None:
    """Test-only: clears accumulated hit state so tests don't leak rate-limit
    state into each other via the shared module-level limiter."""
    _upload_limiter.reset()
