"""Automatic retention cleanup — Security_and_Privacy_v2.md SS3
("Automatic retention window (e.g., 90 days) applies to documents,
derived analysis data, and any temporarily cached embeddings for that
document — corpus embeddings ... are a separate, permanent asset and are
not affected by user document retention rules"). Phase 8 shipped
user-initiated deletion; this is the automatic counterpart.

No in-process scheduler — this module is a callable the standalone
`backend/scripts/run_retention_cleanup.py` entry point invokes, meant to
be triggered by an external scheduler (cron, a platform's scheduled-task
feature, etc.). Matches this project's established "MVP in-process,
single worker, no new distributed infrastructure" precedent
(Technical_Architecture_v2.md SS9) — a scheduler is deployment
infrastructure, not application code, and this repo doesn't have or need
one of its own.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.logging import get_logger, log_event
from app.core.metrics import (
    RETENTION_CLEANUP_RUNS,
    RETENTION_DOCUMENTS_DELETED,
    RETENTION_DOCUMENTS_DELETION_FAILED,
    metrics,
)
from app.models import db_models
from app.services.document_deletion_service import delete_document

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class RetentionCleanupSummary:
    cutoff: datetime
    candidates: int
    deleted: int
    failed: int


def _expired_document_ids(db: Session, cutoff: datetime) -> list:
    return list(db.scalars(select(db_models.Document.id).where(db_models.Document.created_at < cutoff)).all())


def run_retention_cleanup(
    db: Session, *, retention_days: int, upload_dir: str, now: datetime | None = None
) -> RetentionCleanupSummary:
    """Deletes every document whose `created_at` is older than
    `retention_days`, and everything that cascades from it (Phase 8's
    `document_deletion_service.delete_document` — clauses, analyses,
    evidence, entities, matched patterns, the processing job, and the
    stored file). Corpus/reference data is never touched: there is no
    relationship path from `documents` to `corpus_patterns` at all (the
    same structural guarantee `test_document_deletion.py` already proves
    for user-initiated deletion).

    **Idempotent and retry-safe:** re-running this against the same
    database state deletes nothing new (a document already deleted is no
    longer a candidate); a document deleted mid-run by a concurrent
    request is simply not found by a later step and skipped, not an
    error. **Partial-failure-safe:** each document is deleted inside its
    own `Session.begin_nested()` SAVEPOINT (the same per-item isolation
    pattern `risk_scoring_service.score_document` and
    `generation_pipeline_service.generate_pending_explanations` already
    use), so one document's deletion failure (e.g. an unexpected
    filesystem error) rolls back only that document and never blocks the
    rest of the batch. **Observable:** logs a safe event per deletion and
    a summary event at the end (document IDs and counts only — never
    content), and returns a `RetentionCleanupSummary` the calling script
    can act on (e.g. a non-zero exit code if `failed > 0`).
    """
    reference_time = now or datetime.now(UTC)
    cutoff = reference_time - timedelta(days=retention_days)

    candidate_ids = _expired_document_ids(db, cutoff)
    deleted = 0
    failed = 0

    for document_id in candidate_ids:
        try:
            with db.begin_nested():
                document = db.get(db_models.Document, document_id)
                if document is None:
                    # Already gone (deleted by a concurrent request, or by
                    # an earlier, not-yet-committed iteration of this same
                    # run in a caller that batches commits) -- not a
                    # failure, just nothing left to do.
                    continue
                delete_document(db, document, upload_dir)
            deleted += 1
            log_event(
                logger,
                "retention_document_deleted",
                document_id=str(document_id),
                stage="retention",
            )
            metrics.increment(RETENTION_DOCUMENTS_DELETED)
        except Exception:
            failed += 1
            log_event(
                logger,
                "retention_document_deletion_failed",
                document_id=str(document_id),
                stage="retention",
                error_category="retention_cleanup_failure",
            )
            metrics.increment(RETENTION_DOCUMENTS_DELETION_FAILED)

    db.flush()

    log_event(
        logger,
        "retention_cleanup_completed",
        stage="retention",
        count=len(candidate_ids),
    )
    metrics.increment(RETENTION_CLEANUP_RUNS)

    return RetentionCleanupSummary(
        cutoff=cutoff, candidates=len(candidate_ids), deleted=deleted, failed=failed
    )
