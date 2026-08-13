"""FastAPI application entrypoint.

Wires up configuration, safe structured logging, CORS, security headers,
uniform error responses, the health check, document upload/ingestion, and
the report/status/evidence read endpoints.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.documents import router as documents_router
from app.api.health import router as health_router
from app.api.reports import router as reports_router
from app.core.config import get_settings
from app.core.errors import install_exception_handlers
from app.core.logging import configure_logging, get_logger, log_event
from app.models.enums import ErrorCode

settings = get_settings()
configure_logging(settings.log_level)
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # safe_summary() never includes secret values — see core/config.py.
    log_event(logger, "app_startup", environment=settings.safe_summary()["environment"])
    yield


# Plain semantic version, not a phase-tracking label (Phase 10 security
# audit — Security_and_Privacy_v2.md SS1/API SS4: don't expose internal
# development/implementation detail unnecessarily; a `Server`-style
# response header revealing which internal build phase is live is exactly
# that class of leak, even though it's low-severity).
app = FastAPI(title="Financial Contract Risk Reader API", version="0.4.0", lifespan=lifespan)

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


# Standard defensive headers (Phase 10 security audit — API_and_Data_Models.md
# SS4, Security_and_Privacy_v2.md SS9 "no bespoke... enterprise-grade"
# scope discipline: this is the well-established minimal set, not a
# custom scheme). This is a pure JSON API with no user-facing HTML page of
# its own, so there is no cookie/session to protect with SameSite and no
# inline-script surface for a CSP to restrict — X-Frame-Options and
# X-Content-Type-Options are the headers that actually apply here.
@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


# Reject a non-multipart body on the upload route before FastAPI/Starlette
# ever attempts to parse it as a form (Phase 10 security audit,
# pip-audit finding PYSEC-2026-249): the installed starlette version
# (pinned indirectly via fastapi==0.115.6's `starlette<0.42.0` requirement)
# has a known resource-exhaustion issue where `max_fields`/`max_part_size`
# limits are enforced for `multipart/form-data` bodies but silently
# ignored for `application/x-www-form-urlencoded` ones. The upload
# endpoint only ever expects multipart (`UploadFile = File(...)`), so a
# `application/x-www-form-urlencoded` (or any other) content type on that
# path is never legitimate traffic — rejecting it here, in middleware,
# means the request body is never handed to the vulnerable parsing path
# at all. Upgrading starlette itself is out of scope for this phase
# (requires a coordinated fastapi major-version bump — see
# docs/SECURITY_AUDIT.md's accepted-risk entry for the remaining,
# lower-impact advisories in this same family that this narrow fix does
# not address).
_UPLOAD_PATH = "/v1/documents"


@app.middleware("http")
async def reject_non_multipart_upload_body(request: Request, call_next):
    if request.url.path == _UPLOAD_PATH and request.method == "POST":
        content_type = request.headers.get("content-type", "")
        if not content_type.startswith("multipart/form-data"):
            request_id = getattr(request.state, "request_id", uuid.uuid4())
            return JSONResponse(
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                content={
                    "error": {
                        "code": ErrorCode.UNSUPPORTED_FILE_TYPE.value,
                        "user_message": "Only PDF and DOCX files are supported.",
                        "request_id": str(request_id),
                    }
                },
            )
    return await call_next(request)


app.include_router(health_router)
app.include_router(documents_router)
app.include_router(reports_router)
