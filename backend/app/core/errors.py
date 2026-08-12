"""API error response shape — API_and_Data_Models.md SS4.

`{"error": {"code": ErrorCode, "user_message": str, "request_id": uuid}}`

Handlers here never leak stack traces, internal file paths, environment
variables, or database credentials to the client — only the ErrorCode enum
value, a pre-approved user-facing message, and a request ID for internal log
correlation.
"""

from __future__ import annotations

import uuid

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.logging import get_logger, log_event
from app.models.enums import ErrorCode

logger = get_logger(__name__)

# PROVISIONAL_V2: API_and_Data_Models.md SS4 says `user_message` should be
# "the exact pre-approved string from the Security & Access Document" — that
# document doesn't exist in this repository (see PROVISIONAL_DECISIONS.md).
# These are written fresh: short, non-alarming, and compliant with the
# language policy (Security_and_Privacy_v2.md SS7) even though that policy
# is written for clause-risk language, not upload errors.
_DEFAULT_MESSAGES: dict[ErrorCode, str] = {
    ErrorCode.ACCESS_DENIED: "Report not found or you don't have access to it.",
    ErrorCode.RATE_LIMITED: "Too many requests. Please try again shortly.",
    ErrorCode.INTERNAL_ERROR: "Something went wrong on our end. Please try again.",
    ErrorCode.FILE_TOO_LARGE: "This file is too large (or has too many pages) to process.",
    ErrorCode.UNSUPPORTED_FILE_TYPE: "Only PDF and DOCX files are supported.",
    ErrorCode.CORRUPTED_FILE: "This file could not be read. It may be corrupted or damaged.",
    ErrorCode.PASSWORD_PROTECTED: "This file is password-protected. Please upload an unprotected copy.",
    ErrorCode.LOW_TEXT_CONTENT: "We couldn't find enough readable text in this document — it may be a scanned "
    "or image-only file.",
}


class ApiError(Exception):
    """Raise to produce the canonical `{"error": {...}}` response shape
    (API_and_Data_Models.md SS4) from anywhere in a request — e.g. upload
    validation/parsing failures. Never raise this with a message derived
    from parser internals or an exception's `str()`; `user_message` must
    always be a pre-approved, safe string.
    """

    def __init__(self, code: ErrorCode, status_code: int, user_message: str | None = None) -> None:
        self.code = code
        self.status_code = status_code
        self.user_message = user_message or _DEFAULT_MESSAGES.get(
            code, _DEFAULT_MESSAGES[ErrorCode.INTERNAL_ERROR]
        )
        super().__init__(code.value)


def _error_body(code: ErrorCode, user_message: str, request_id: uuid.UUID) -> dict:
    return {
        "error": {
            "code": code.value,
            "user_message": user_message,
            "request_id": str(request_id),
        }
    }


def install_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def handle_api_error(request: Request, exc: ApiError) -> JSONResponse:
        request_id = getattr(request.state, "request_id", uuid.uuid4())
        log_event(
            logger,
            "api_error",
            request_id=str(request_id),
            error_code=exc.code.value,
            status_code=exc.status_code,
            http_path=str(request.url.path),
            http_method=request.method,
        )
        return JSONResponse(
            status_code=exc.status_code,
            content=_error_body(exc.code, exc.user_message, request_id),
        )

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_exception(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        request_id = getattr(request.state, "request_id", uuid.uuid4())
        code = ErrorCode.ACCESS_DENIED if exc.status_code == 404 else ErrorCode.INTERNAL_ERROR
        message = exc.detail if isinstance(exc.detail, str) else _DEFAULT_MESSAGES[ErrorCode.INTERNAL_ERROR]
        log_event(
            logger,
            "http_exception",
            request_id=str(request_id),
            status_code=exc.status_code,
            http_path=str(request.url.path),
            http_method=request.method,
        )
        return JSONResponse(
            status_code=exc.status_code,
            content=_error_body(code, message, request_id),
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        request_id = getattr(request.state, "request_id", uuid.uuid4())
        log_event(
            logger,
            "validation_error",
            request_id=str(request_id),
            http_path=str(request.url.path),
            http_method=request.method,
            status_code=422,
        )
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content=_error_body(
                ErrorCode.INTERNAL_ERROR,
                "The request could not be processed.",
                request_id,
            ),
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_exception(request: Request, exc: Exception) -> JSONResponse:
        request_id = getattr(request.state, "request_id", uuid.uuid4())
        # Only the exception *type* is logged, never str(exc) or a traceback —
        # both can incidentally contain sensitive values from local variables
        # (Security_and_Privacy_v2.md SS6).
        log_event(
            logger,
            "unhandled_exception",
            level=40,  # logging.ERROR, avoiding an extra import for one constant
            request_id=str(request_id),
            error_category=type(exc).__name__,
            http_path=str(request.url.path),
            http_method=request.method,
            status_code=500,
        )
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=_error_body(
                ErrorCode.INTERNAL_ERROR,
                _DEFAULT_MESSAGES[ErrorCode.INTERNAL_ERROR],
                request_id,
            ),
        )
