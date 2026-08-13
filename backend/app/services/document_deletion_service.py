"""Shared document-deletion logic — Security_and_Privacy_v2.md SS3
("Documents and all derived data ... are deletable by the access-token
holder on request"). Used by both `DELETE /v1/documents/{id}` (Phase 10,
user-initiated) and `retention_service.py` (Phase 11, automatic
retention-window cleanup) so the two call sites can never drift apart on
what "delete a document" actually does.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import db_models
from app.services import storage


def delete_document(db: Session, document: db_models.Document, upload_dir: str) -> None:
    """Deletes the `documents` row first (cascading, via the existing
    `cascade="all, delete-orphan"` ORM relationships and `ondelete="CASCADE"`
    foreign keys, to `clauses` -> `clause_analyses` -> `evidence_spans`/
    `financial_entities`/`matched_patterns`, and to `processing_jobs`), then
    best-effort removes the stored original file. Never touches
    `corpus_patterns` — no relationship path from `documents` reaches it,
    and `matched_patterns.corpus_pattern_id` is `ondelete="RESTRICT"`, so a
    corpus pattern referenced by a (now-deleted) match cannot itself be
    deleted by this or any caller.

    Ordered this way (DB row first, file cleanup second) so a deletion
    request — whether from the access-token holder or the automatic
    retention job — is honored even if the best-effort file cleanup that
    follows encounters an unexpected filesystem error. Does not commit —
    callers control the transaction boundary (the API's `Depends(get_db)`
    commits after the request; the retention job commits per-document, for
    per-document failure isolation).
    """
    storage_path = document.storage_path
    db.delete(document)
    db.flush()
    if storage_path:
        storage.delete_document_file(upload_dir, storage_path)
