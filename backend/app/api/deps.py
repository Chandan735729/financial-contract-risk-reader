"""Shared FastAPI dependency providers for the read/report/status endpoints
and the analysis pipeline (Phase 8).

Two concerns live here:
  1. Process-singleton providers for `EmbeddingService`/`ChromaVectorStore`
     (same "load once, reuse across requests" pattern `db/session.py` already
     uses for the engine/session factory — the embedding model in particular
     is expensive to load and must never be reloaded per request, Phase 4
     spec SS8/SS22).
  2. `require_document_access` — the single, shared access-token check every
     document-scoped read endpoint depends on, so authorization can never be
     accidentally skipped by a new endpoint forgetting to check it
     (Security_and_Privacy_v2.md SS4: "every ... read inherits authorization
     from the parent documents row, with no direct access path that skips
     that check").
"""

from __future__ import annotations

import hmac
import uuid
from functools import lru_cache

from fastapi import Depends, Header, status
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.errors import ApiError
from app.db.session import get_db
from app.models import db_models
from app.models.enums import ErrorCode
from app.services.embedding_service import EmbeddingService
from app.services.llm_client import GenerationLLMClient
from app.services.retrieval.vector_store import ChromaVectorStore, create_client


@lru_cache(maxsize=1)
def _embedding_service_singleton(model_name: str) -> EmbeddingService:
    return EmbeddingService(model_name)


def get_embedding_service(settings: Settings = Depends(get_settings)) -> EmbeddingService:
    return _embedding_service_singleton(settings.embedding_model_name)


@lru_cache(maxsize=1)
def _vector_store_singleton(persist_dir: str) -> ChromaVectorStore:
    return ChromaVectorStore(create_client(persist_dir))


def get_vector_store(settings: Settings = Depends(get_settings)) -> ChromaVectorStore:
    return _vector_store_singleton(settings.chroma_persist_dir)


def get_llm_client() -> GenerationLLMClient | None:
    """`None` by default -- `generate_pending_explanations` (Phase 7)
    already lazily builds the real Anthropic-backed client itself, only
    once a HIGH/MEDIUM clause actually needs one (cost control). Exposed as
    its own dependency purely so tests can override it with a scripted
    fake client and exercise the real generation/grounding path end-to-end
    through the HTTP API, without ever making a live API call."""
    return None


def _tokens_match(provided: str, actual: str) -> bool:
    # Constant-time comparison — an unguessable token is only as good as a
    # timing-safe check of it (Security_and_Privacy_v2.md SS4).
    return hmac.compare_digest(provided, actual)


_BEARER_PREFIX = "Bearer "


def _extract_bearer_token(authorization: str | None) -> str | None:
    if not authorization or not authorization.startswith(_BEARER_PREFIX):
        return None
    token = authorization[len(_BEARER_PREFIX) :].strip()
    return token or None


def require_document_access(
    document_id: uuid.UUID,
    db: Session = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> db_models.Document:
    """Shared authorization dependency for every document-scoped read
    endpoint. Deliberately returns the *same* `ErrorCode.ACCESS_DENIED` /
    404 for "document not found", "missing token", and "wrong token" —
    never distinguishing them in the response, so a caller can't use the
    error to enumerate valid document IDs (Security_and_Privacy_v2.md SS4).

    The token travels as `Authorization: Bearer <token>`, never a query
    parameter: API_and_Data_Models.md never specifies the transport
    mechanism, and a query-string token is a well-known leak vector (default
    web-server/reverse-proxy access logs, browser history, `Referer`
    headers all capture full URLs, but not headers) — this was found
    empirically by this phase's own logging-safety test, not assumed in
    advance. See docs/PROVISIONAL_DECISIONS.md "Phase 8: access token
    transport".
    """
    access_token = _extract_bearer_token(authorization)
    document = db.get(db_models.Document, document_id)
    if document is None or not access_token or not _tokens_match(access_token, document.access_token):
        raise ApiError(ErrorCode.ACCESS_DENIED, status.HTTP_404_NOT_FOUND)
    return document
