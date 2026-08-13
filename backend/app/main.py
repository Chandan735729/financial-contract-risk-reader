"""FastAPI application entrypoint.

Wires up configuration, safe structured logging, CORS, uniform error
responses, the health check, and document upload/ingestion (Phase 2). No
report/pipeline endpoints exist yet (those are later phases per
Implementation_Roadmap.md).
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.api.documents import router as documents_router
from app.api.health import router as health_router
from app.api.reports import router as reports_router
from app.core.config import get_settings
from app.core.errors import install_exception_handlers
from app.core.logging import configure_logging, get_logger, log_event

settings = get_settings()
configure_logging(settings.log_level)
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # safe_summary() never includes secret values — see core/config.py.
    log_event(logger, "app_startup", environment=settings.safe_summary()["environment"])
    yield


app = FastAPI(title="Financial Contract Risk Reader API", version="0.2.0-phase2", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

install_exception_handlers(app)


@app.middleware("http")
async def assign_request_id(request: Request, call_next):
    request_id = uuid.uuid4()
    request.state.request_id = request_id
    response = await call_next(request)
    response.headers["X-Request-ID"] = str(request_id)
    return response


app.include_router(health_router)
app.include_router(documents_router)
app.include_router(reports_router)
