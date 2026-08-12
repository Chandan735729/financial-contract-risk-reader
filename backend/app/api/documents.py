"""`POST /documents` — document upload (API_and_Data_Models.md SS3).

Flow: stream-read within the size cap -> sniff real file type from bytes
(never trust filename/extension/Content-Type) -> parse fully in-memory ->
only on a successful parse, write to permanent storage and create the
`documents`/`processing_jobs` rows. A validation or parsing failure never
creates a document, never writes to storage, and returns the canonical
`{"error": {...}}` shape via `ApiError` — see Phase 2 spec SS1, SS14.
"""

from __future__ import annotations

import secrets
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, File, UploadFile, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.errors import ApiError
from app.core.logging import get_logger, log_event
from app.db.session import get_db
from app.models import db_models
from app.models.enums import DocumentType, ErrorCode, ProcessingStage
from app.models.schemas import DocumentUploadResponse
from app.services import storage
from app.services.parsing.detection import detect_file_kind
from app.services.parsing.docx_parser import parse_docx
from app.services.parsing.models import ParseResult
from app.services.parsing.pdf_parser import parse_pdf

router = APIRouter(prefix="/v1/documents", tags=["documents"])
logger = get_logger(__name__)

# UploadFile wraps a SpooledTemporaryFile; reading in fixed chunks bounds
# peak memory and lets the size cap abort a huge upload without ever
# buffering more than `settings.max_upload_size_bytes` (Phase 2 spec SS15).
_UPLOAD_READ_CHUNK_SIZE = 1024 * 1024  # 1 MB

_STATUS_CODE_BY_ERROR_CODE: dict[ErrorCode, int] = {
    ErrorCode.FILE_TOO_LARGE: status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
    ErrorCode.UNSUPPORTED_FILE_TYPE: status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
    ErrorCode.CORRUPTED_FILE: status.HTTP_422_UNPROCESSABLE_ENTITY,
    ErrorCode.PASSWORD_PROTECTED: status.HTTP_422_UNPROCESSABLE_ENTITY,
    ErrorCode.LOW_TEXT_CONTENT: status.HTTP_422_UNPROCESSABLE_ENTITY,
}


def _status_code_for(code: ErrorCode) -> int:
    return _STATUS_CODE_BY_ERROR_CODE.get(code, status.HTTP_422_UNPROCESSABLE_ENTITY)


async def _read_upload_within_limit(file: UploadFile, max_bytes: int) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await file.read(_UPLOAD_READ_CHUNK_SIZE)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise ApiError(ErrorCode.FILE_TOO_LARGE, status.HTTP_413_REQUEST_ENTITY_TOO_LARGE)
        chunks.append(chunk)
    return b"".join(chunks)


def _parse(kind: str, data: bytes, settings: Settings) -> ParseResult:
    if kind == "pdf":
        return parse_pdf(
            data,
            max_pages=settings.max_pdf_pages,
            min_text_chars=settings.min_text_chars,
            min_avg_chars_per_page=settings.min_avg_chars_per_page,
        )
    return parse_docx(data, max_items=settings.max_docx_paragraphs, min_text_chars=settings.min_text_chars)


@router.post("", response_model=DocumentUploadResponse, status_code=status.HTTP_201_CREATED)
async def upload_document(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> DocumentUploadResponse:
    data = await _read_upload_within_limit(file, settings.max_upload_size_bytes)

    if not data:
        raise ApiError(ErrorCode.CORRUPTED_FILE, status.HTTP_422_UNPROCESSABLE_ENTITY)

    # Real content sniffed from bytes — filename/extension/Content-Type are
    # never trusted (Phase 2 spec SS2; Security_and_Privacy_v2.md SS2).
    kind = detect_file_kind(data)
    if kind == "unknown":
        raise ApiError(ErrorCode.UNSUPPORTED_FILE_TYPE, status.HTTP_415_UNSUPPORTED_MEDIA_TYPE)

    parse_result = _parse(kind, data, settings)
    if not parse_result.is_success:
        error_code = parse_result.error_code or ErrorCode.INTERNAL_ERROR
        raise ApiError(error_code, _status_code_for(error_code))

    document_id = uuid.uuid4()
    # 48 random bytes -> 64-char urlsafe-base64 token, filling the
    # `access_token` column exactly (Security_and_Privacy_v2.md SS4
    # unguessable per-document token; generation site deferred from Phase 0 —
    # see PROVISIONAL_DECISIONS.md).
    access_token = secrets.token_urlsafe(48)

    try:
        storage_filename = storage.save_document_file(settings.upload_dir, document_id, kind, data)
    except OSError:
        log_event(logger, "upload_storage_write_failed", document_id=str(document_id), stage="parsing")
        raise ApiError(ErrorCode.INTERNAL_ERROR, status.HTTP_500_INTERNAL_SERVER_ERROR) from None

    parsed = parse_result.document
    document = db_models.Document(
        id=document_id,
        access_token=access_token,
        original_filename=storage.sanitize_original_filename(file.filename),
        storage_path=storage_filename,
        file_format=kind,
        file_size_bytes=len(data),
        page_count=parsed.page_count if parsed else None,
        document_type=DocumentType.UNKNOWN,  # Phase 2 never infers loan/insurance from content.
    )
    job = db_models.ProcessingJob(
        id=uuid.uuid4(),
        document_id=document_id,
        # Parsing already completed successfully in this request; SEGMENTING
        # reflects the pipeline's next stage, which Phase 3 implements.
        stage=ProcessingStage.SEGMENTING,
        started_at=datetime.now(UTC),
    )

    db.add(document)
    db.add(job)
    try:
        # Flush (not commit) so an IntegrityError surfaces here, inside this
        # try/except, where the just-written storage file can still be
        # cleaned up — the final commit happens in the `get_db` dependency
        # after this function returns (Phase 2 spec SS14).
        db.flush()
    except IntegrityError:
        db.rollback()
        storage.delete_document_file(settings.upload_dir, storage_filename)
        log_event(logger, "upload_db_write_failed", document_id=str(document_id), stage="parsing")
        raise ApiError(ErrorCode.INTERNAL_ERROR, status.HTTP_500_INTERNAL_SERVER_ERROR) from None

    log_event(
        logger,
        "document_uploaded",
        document_id=str(document_id),
        stage="parsing",
        document_type=DocumentType.UNKNOWN.value,
    )

    return DocumentUploadResponse(document_id=document_id, access_token=access_token)
