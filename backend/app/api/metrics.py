"""`GET /metrics` — safe operational aggregates (Phase 11).

Exposes the in-process counters/durations `app/core/metrics.py` accumulates:
uploads, completed/failed pipeline jobs and their durations, generation
failures, grounding-fallback usage, rate-limit rejections, and retention
cleanup events. Every value is a count or a duration statistic — there is no
code path from any per-document/per-user field to this endpoint, so there is
nothing here that needs redaction the way `/v1/documents/*` responses do.

Unauthenticated, matching `/health` and `/health/ready` (an operator's
monitoring/scraping tooling needs to reach this without a per-document
access token, which is the only auth mechanism this MVP has — see
docs/PROVISIONAL_DECISIONS.md P11.2). Safe to expose publicly: it reveals
only aggregate operational volume, never which documents exist, what they
say, or who uploaded them.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.core.metrics import metrics

router = APIRouter()


@router.get("/metrics")
def get_metrics() -> dict[str, object]:
    return metrics.snapshot()
