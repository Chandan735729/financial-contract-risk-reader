"""`GET /health` (liveness) and `GET /health/ready` (readiness) — Phase 11
operational-readiness split.

Liveness (`/health`, unchanged since Phase 0) answers "is the process
running at all" — no dependency checks, always fast, always safe to hit
even if the database or vector store is down (an orchestrator should not
restart a healthy process just because a downstream dependency is
temporarily unavailable — that's what readiness is for).

Readiness (`/health/ready`) answers "can this instance actually serve
traffic right now" — it checks the dependencies a request would actually
need (PostgreSQL, the Chroma vector store; configuration is checked
implicitly, since `Settings` already fails fast at process startup via
`_validate_production_requirements` — there is nothing further to probe at
request time). Returns 503 (not 200) when any check fails, so a load
balancer or orchestrator can route around this instance.

Both endpoints return only a boolean status per dependency — never an
exception message, stack trace, connection string, or any other internal
detail (Security_and_Privacy_v2.md SS1/SS9). A readiness probe is commonly
polled unauthenticated by infrastructure, so it must never become a
diagnostic-information leak.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.deps import get_vector_store
from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.models.schemas import HealthResponse, ReadinessCheckResult, ReadinessResponse
from app.services.retrieval.vector_store import ChromaVectorStore

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
def health(settings: Settings = Depends(get_settings)) -> HealthResponse:
    return HealthResponse(status="ok", environment=settings.environment.value)


@router.get("/health/ready", response_model=ReadinessResponse)
def readiness(
    response: Response,
    db: Session = Depends(get_db),
    vector_store: ChromaVectorStore = Depends(get_vector_store),
) -> ReadinessResponse:
    checks: dict[str, ReadinessCheckResult] = {}

    try:
        db.execute(text("SELECT 1"))
        checks["database"] = ReadinessCheckResult(ok=True)
    except Exception:
        checks["database"] = ReadinessCheckResult(ok=False)

    try:
        vector_store.ping()
        checks["vector_store"] = ReadinessCheckResult(ok=True)
    except Exception:
        checks["vector_store"] = ReadinessCheckResult(ok=False)

    ready = all(check.ok for check in checks.values())
    if not ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return ReadinessResponse(ready=ready, checks=checks)
