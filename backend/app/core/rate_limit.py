"""In-process upload rate limiting — Security_and_Privacy_v2.md SS8
("Upload rate limiting per session/IP"), a requirement carried over from
the (unavailable) v1 doc but never actually implemented until this phase
(Phase 10 security audit found `ErrorCode.RATE_LIMITED` defined and wired
into every error-mapping table, but nothing ever raised it).

Deliberately a simple in-memory fixed-window counter keyed by client IP —
no Redis/external dependency, matching this project's established
"MVP in-process, single worker" precedent (Technical_Architecture_v2.md
SS9, reused for Phase 8's background pipeline).

**Documented, unresolved-by-design limitation (docs/SECURITY_AUDIT.md
SS5):** state is per-worker-process. A multi-worker or multi-instance
deployment needs a shared store (e.g. Redis) for a true global limit —
explicitly out of scope per Security_and_Privacy_v2.md SS9 "Do-Not-Over-
Engineer Notes" for this MVP phase. Single-instance, single-worker
deployment (the only configuration this repository's operational docs
recommend — see docs/DEPLOYMENT_CHECKLIST.md) does not hit this limitation
at all: there is exactly one process, so "per-process" and "global" are
the same thing.

**Proxy IP resolution (`resolve_client_ip`, Phase 11):** `X-Forwarded-For`
is attacker-controlled input — a client can set it to anything before the
request ever reaches a reverse proxy — so it is never honored unless
`Settings.trust_proxy_headers` is explicitly set `True` for a deployment
that actually sits behind exactly one trusted reverse proxy. When trusted,
only the *rightmost* entry in the header is used: that is the address the
trusted proxy itself observed as its direct peer (each hop a request
passes through appends its observed peer address to the end of the list,
so everything left of the last entry — including a value an attacker
supplied directly — is unverified). This models exactly one trusted proxy
hop; a deployment with more than one hop of trusted proxying (e.g. a CDN
in front of a load balancer) would need to trust more than one entry from
the right, which is not implemented here and not needed by the documented
Vercel/Railway-or-Render deployment shape (Technical_Architecture_v2.md
SS9's "Unchanged from v1" architecture) this MVP targets. With
`trust_proxy_headers=False` (the default), the header is ignored entirely
and `request.client.host` (the direct TCP peer) is used — correct, and
the only safe choice, when there is no trusted proxy in front of the app.
"""

from __future__ import annotations

import time
from collections import defaultdict, deque

from fastapi import Depends, Request, status

from app.core.config import Settings, get_settings
from app.core.errors import ApiError
from app.core.metrics import UPLOAD_RATE_LIMIT_REJECTIONS, metrics
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


def resolve_client_ip(request: Request, settings: Settings) -> str:
    """The address to rate-limit by. See the module docstring for the full
    trust-boundary rationale — summary: `X-Forwarded-For` is only ever
    consulted when `settings.trust_proxy_headers` is `True`, and even then
    only its rightmost entry (the one hop of trusted proxying this MVP
    models) is used. Otherwise, and whenever the header is absent, falls
    back to the direct TCP peer address.
    """
    if settings.trust_proxy_headers:
        forwarded_for = request.headers.get("x-forwarded-for")
        if forwarded_for:
            candidates = [part.strip() for part in forwarded_for.split(",") if part.strip()]
            if candidates:
                return candidates[-1]
    return request.client.host if request.client else "unknown"


def enforce_upload_rate_limit(request: Request, settings: Settings = Depends(get_settings)) -> None:
    """FastAPI dependency — raises `ErrorCode.RATE_LIMITED` (429) once a
    client exceeds `settings.upload_rate_limit_max_requests` uploads per
    `settings.upload_rate_limit_window_seconds`.
    """
    allowed = _upload_limiter.allow(
        resolve_client_ip(request, settings),
        max_requests=settings.upload_rate_limit_max_requests,
        window_seconds=settings.upload_rate_limit_window_seconds,
    )
    if not allowed:
        metrics.increment(UPLOAD_RATE_LIMIT_REJECTIONS)
        raise ApiError(ErrorCode.RATE_LIMITED, status.HTTP_429_TOO_MANY_REQUESTS)


def reset_upload_rate_limiter() -> None:
    """Test-only: clears accumulated hit state so tests don't leak rate-limit
    state into each other via the shared module-level limiter."""
    _upload_limiter.reset()
