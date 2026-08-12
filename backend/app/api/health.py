"""GET /health — liveness/readiness check.

Returns only a status flag and environment label. Never exposes environment
variables, database credentials, stack traces, internal filesystem paths, or
any other infrastructure detail.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.core.config import Settings, get_settings
from app.models.schemas import HealthResponse

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
def health(settings: Settings = Depends(get_settings)) -> HealthResponse:
    return HealthResponse(status="ok", environment=settings.environment.value)
