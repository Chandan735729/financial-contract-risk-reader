"""End-to-end contract analysis pipeline orchestrator — Phase 8.

Wires the already-built, already-tested Phase 2-7 services into one
sequence, driven by the `ProcessingJob.stage` state machine
(`ProcessingStage`: QUEUED -> PARSING -> SEGMENTING -> UNDERSTANDING ->
SCORING -> GENERATING -> VERIFYING -> COMPLETED, or -> FAILED). This module
owns *sequencing, persistence checkpoints, and failure isolation only* — it
never re-implements or alters the decision logic of any stage:

  - Parsing:        `app.services.parsing.pdf_parser` / `docx_parser` (Phase 2)
  - Segmentation:    `app.services.segmentation_service` (Phase 3)
  - Understanding:   `app.services.clause_understanding_service` (Phase 4)
  - Risk scoring:    `app.services.risk_scoring_service` (Phase 5, incl. Evidence Engine)
  - Generation:       `app.services.generation_pipeline_service` (Phase 7, incl. Grounding Guard)

**Why PARSING re-runs the parser instead of reusing the upload request's
in-memory result:** parsed text is deliberately never persisted (Phase 2
spec; docs/PROVISIONAL_DECISIONS.md "Phase 2: parsed text is not
persisted") — the *only* way to get a `ParsedDocument` back is to re-read
the stored original and re-parse it with the exact same Phase 2 functions.
This also makes the pipeline runnable from just a `document_id`, which is
what makes it safely resumable (see idempotency below).

**Idempotency ("implement only what's necessary" — Phase 8 spec):** no new
tracking table or distributed idempotency system. `job.stage` is itself the
durable checkpoint — each stage's work is fully flushed before `job.stage`
advances past it. A second call for the same `document_id` (duplicate
trigger, or a resumed run after a crash) compares its own `job.stage`
against each stage's position in `_STAGE_ORDER` and skips any stage already
behind it, reusing the `Clause`/`ClauseAnalysisORM` rows a prior run already
persisted rather than re-deriving/re-inserting them. This matters because
`segmentation_service.persist_clauses` and
`clause_understanding_service`'s entity/retrieval persistence helpers
insert unconditionally (correct for their own single-pass contract) and
would otherwise duplicate rows on a second pass; scoring and generation are
in-place updates on an existing row and were already safe either way.

**Failure isolation:** PARSING/SEGMENTING failures are document-level (a
document that can't be parsed or produces zero clauses has nothing to
isolate around) and mark the whole job FAILED with a safe `ErrorCode`.
UNDERSTANDING failures are isolated per clause inside a `Session.begin_nested()`
SAVEPOINT (mirroring the pattern `risk_scoring_service.score_document` and
`generation_pipeline_service.generate_pending_explanations` already use for
their own per-clause loops) — one clause's retrieval/entity/condition
extraction failure rolls back only that clause's pending analysis row,
which `score_document`'s existing `analysis is None -> skipped_unanalyzed`
path already treats as a safe, expected state. SCORING and GENERATING reuse
their own already-built per-clause SAVEPOINT isolation unchanged.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.core.logging import get_logger, log_event
from app.models import db_models
from app.models.enums import ErrorCode, ProcessingStage
from app.services import segmentation_service, storage
from app.services.clause_understanding_service import run_clause_understanding
from app.services.embedding_service import EmbeddingService
from app.services.generation_pipeline_service import (
    DocumentGenerationSummary,
    generate_pending_explanations,
)
from app.services.llm_client import GenerationLLMClient
from app.services.parsing.docx_parser import parse_docx
from app.services.parsing.models import ParseResult
from app.services.parsing.pdf_parser import parse_pdf
from app.services.retrieval.vector_store import ChromaVectorStore
from app.services.risk_scoring_service import DocumentScoringSummary, score_document

logger = get_logger(__name__)

_STAGE_ORDER: tuple[ProcessingStage, ...] = (
    ProcessingStage.QUEUED,
    ProcessingStage.PARSING,
    ProcessingStage.SEGMENTING,
    ProcessingStage.UNDERSTANDING,
    ProcessingStage.SCORING,
    ProcessingStage.GENERATING,
    ProcessingStage.VERIFYING,
    ProcessingStage.COMPLETED,
)


def _rank(stage: ProcessingStage) -> int:
    return _STAGE_ORDER.index(stage)


@dataclass(frozen=True, slots=True)
class PipelineOutcome:
    document_id: uuid.UUID
    final_stage: ProcessingStage
    error_code: str | None
    clause_count: int
    understanding_failed: int
    scoring: DocumentScoringSummary | None
    generation: DocumentGenerationSummary | None


def _parse_stored_document(kind: str, data: bytes, settings: Settings) -> ParseResult:
    """Same dispatch `app.api.documents._parse` uses at upload time — kept as
    a tiny, deliberately duplicated 2-line dispatch (not imported from the
    `api` layer, which a service module must not depend on) rather than
    duplicating any actual parsing logic, which stays exclusively in
    `parse_pdf`/`parse_docx`."""
    if kind == "pdf":
        return parse_pdf(
            data,
            max_pages=settings.max_pdf_pages,
            min_text_chars=settings.min_text_chars,
            min_avg_chars_per_page=settings.min_avg_chars_per_page,
        )
    return parse_docx(data, max_items=settings.max_docx_paragraphs, min_text_chars=settings.min_text_chars)


def _mark_failed(db: Session, job: db_models.ProcessingJob, error_code: ErrorCode) -> None:
    job.stage = ProcessingStage.FAILED
    job.error_code = error_code.value
    job.completed_at = datetime.now(UTC)
    db.flush()


def run_analysis_pipeline(
    db: Session,
    document_id: uuid.UUID,
    *,
    settings: Settings,
    embedding_service: EmbeddingService,
    vector_store: ChromaVectorStore,
    llm_client: GenerationLLMClient | None = None,
) -> PipelineOutcome:
    """Runs (or resumes) the full analysis pipeline for one document. Never
    raises for an ordinary processing failure (parse/segmentation/clause
    error) — those are recorded on `job.stage`/`job.error_code` and reported
    back via `PipelineOutcome`. Raises only `LookupError` if `document_id`
    doesn't correspond to an existing `Document`/`ProcessingJob` pair, which
    is a caller bug (the background task and any retry path only ever pass
    an ID that was just created in the same transaction).
    """
    document = db.get(db_models.Document, document_id)
    job = db.scalars(
        select(db_models.ProcessingJob).where(db_models.ProcessingJob.document_id == document_id)
    ).one_or_none()
    if document is None or job is None:
        raise LookupError(f"no document/processing job found for {document_id}")

    if job.stage == ProcessingStage.COMPLETED:
        total = len(
            db.scalars(select(db_models.Clause).where(db_models.Clause.document_id == document_id)).all()
        )
        return PipelineOutcome(
            document_id=document_id,
            final_stage=ProcessingStage.COMPLETED,
            error_code=None,
            clause_count=total,
            understanding_failed=0,
            scoring=None,
            generation=None,
        )
    if job.stage == ProcessingStage.FAILED:
        return PipelineOutcome(
            document_id=document_id,
            final_stage=ProcessingStage.FAILED,
            error_code=job.error_code,
            clause_count=0,
            understanding_failed=0,
            scoring=None,
            generation=None,
        )

    pipeline_start = time.monotonic()
    current_rank = _rank(job.stage)
    understanding_failed = 0
    scoring_summary: DocumentScoringSummary | None = None
    generation_summary: DocumentGenerationSummary | None = None

    # ---- PARSING + SEGMENTING (document-level; resumed runs skip this if
    # clauses already exist from a prior pass) ----
    if current_rank <= _rank(ProcessingStage.SEGMENTING):
        stage_start = time.monotonic()
        storage_path = document.storage_path
        file_format = document.file_format
        if storage_path is None or file_format is None or file_format not in ("pdf", "docx"):
            _mark_failed(db, job, ErrorCode.CORRUPTED_FILE)
            return PipelineOutcome(document_id, ProcessingStage.FAILED, job.error_code, 0, 0, None, None)

        job.stage = ProcessingStage.PARSING
        db.flush()
        try:
            data = storage.load_document_file(settings.upload_dir, storage_path)
        except OSError:
            log_event(logger, "pipeline_storage_read_failed", document_id=str(document_id), stage="parsing")
            _mark_failed(db, job, ErrorCode.INTERNAL_ERROR)
            return PipelineOutcome(document_id, ProcessingStage.FAILED, job.error_code, 0, 0, None, None)

        parse_result = _parse_stored_document(file_format, data, settings)
        if not parse_result.is_success or parse_result.document is None:
            error_code = parse_result.error_code or ErrorCode.INTERNAL_ERROR
            _mark_failed(db, job, error_code)
            return PipelineOutcome(document_id, ProcessingStage.FAILED, job.error_code, 0, 0, None, None)

        log_event(
            logger,
            "pipeline_stage_completed",
            document_id=str(document_id),
            stage="parsing",
            duration_ms=int((time.monotonic() - stage_start) * 1000),
        )

        job.stage = ProcessingStage.SEGMENTING
        db.flush()
        stage_start = time.monotonic()
        seg_result = segmentation_service.segment_document(parse_result.document)
        segmentation_service.persist_clauses(db, document_id, seg_result)
        db.flush()
        log_event(
            logger,
            "pipeline_stage_completed",
            document_id=str(document_id),
            stage="segmenting",
            duration_ms=int((time.monotonic() - stage_start) * 1000),
            count=len(seg_result.clauses),
            low_confidence_flag=seg_result.low_confidence_flag,
        )
        if job.stage == ProcessingStage.FAILED:
            # persist_clauses already set FAILED/SEGMENTATION_LOW_CONFIDENCE
            # for a zero-clause result — nothing further to isolate around.
            job.completed_at = datetime.now(UTC)
            db.flush()
            return PipelineOutcome(document_id, ProcessingStage.FAILED, job.error_code, 0, 0, None, None)
        current_rank = _rank(job.stage)

    clauses = db.scalars(select(db_models.Clause).where(db_models.Clause.document_id == document_id)).all()

    # ---- UNDERSTANDING (per-clause isolation) ----
    if current_rank <= _rank(ProcessingStage.UNDERSTANDING):
        stage_start = time.monotonic()
        for clause in clauses:
            try:
                with db.begin_nested():
                    run_clause_understanding(
                        db,
                        clause,
                        document_type=document.document_type,
                        taxonomy_version=settings.taxonomy_version,
                        corpus_version=settings.corpus_version,
                        embedding_service=embedding_service,
                        vector_store=vector_store,
                        top_k=settings.retrieval_top_k,
                        min_similarity_floor=settings.retrieval_min_similarity_floor,
                        min_lexical_floor=settings.retrieval_min_lexical_floor,
                    )
            except Exception:
                understanding_failed += 1
                log_event(
                    logger,
                    "clause_understanding_pipeline_failed",
                    document_id=str(document_id),
                    clause_id=str(clause.id),
                    stage="understanding",
                    error_category="understanding_failure",
                )
        db.flush()
        log_event(
            logger,
            "pipeline_stage_completed",
            document_id=str(document_id),
            stage="understanding",
            duration_ms=int((time.monotonic() - stage_start) * 1000),
            count=len(clauses),
        )
        job.stage = ProcessingStage.SCORING
        db.flush()
        current_rank = _rank(job.stage)

    # ---- SCORING (Risk Engine + Evidence Engine; per-clause isolation
    # already built into score_document, reused unchanged) ----
    if current_rank <= _rank(ProcessingStage.SCORING):
        stage_start = time.monotonic()
        scoring_summary = score_document(db, document_id, document_type=document.document_type)
        log_event(
            logger,
            "pipeline_stage_completed",
            document_id=str(document_id),
            stage="scoring",
            duration_ms=int((time.monotonic() - stage_start) * 1000),
            count=scoring_summary.scored,
        )
        job.stage = ProcessingStage.GENERATING
        db.flush()
        current_rank = _rank(job.stage)

    # ---- GENERATING + VERIFYING (grounded explanation + grounding guard;
    # per-clause isolation and grounding verification already built into
    # generate_pending_explanations, reused unchanged. Generation and
    # verification happen together, synchronously, per clause inside that
    # call -- there is no separately-persisted intermediate state between
    # them to expose, so VERIFYING is set as a checkpoint immediately after
    # generation returns, not a separately timed phase.) ----
    if current_rank <= _rank(ProcessingStage.VERIFYING):
        stage_start = time.monotonic()
        generation_summary = generate_pending_explanations(
            db, document_id, document_type=document.document_type, settings=settings, client=llm_client
        )
        log_event(
            logger,
            "pipeline_stage_completed",
            document_id=str(document_id),
            stage="generating",
            duration_ms=int((time.monotonic() - stage_start) * 1000),
            count=generation_summary.eligible,
        )
        job.stage = ProcessingStage.VERIFYING
        db.flush()

    job.stage = ProcessingStage.COMPLETED
    job.error_code = None
    job.completed_at = datetime.now(UTC)
    db.flush()

    log_event(
        logger,
        "pipeline_completed",
        document_id=str(document_id),
        stage=job.stage.value,
        duration_ms=int((time.monotonic() - pipeline_start) * 1000),
        count=len(clauses),
    )

    return PipelineOutcome(
        document_id=document_id,
        final_stage=ProcessingStage.COMPLETED,
        error_code=None,
        clause_count=len(clauses),
        understanding_failed=understanding_failed,
        scoring=scoring_summary,
        generation=generation_summary,
    )


def run_analysis_pipeline_in_background(
    session_factory: sessionmaker[Session],
    document_id: uuid.UUID,
    *,
    settings: Settings,
    embedding_service: EmbeddingService,
    vector_store: ChromaVectorStore,
    llm_client: GenerationLLMClient | None = None,
) -> None:
    """`BackgroundTasks` entry point (Phase 8: "background task processing
    ... single-document-at-a-time per worker for MVP", Technical_Architecture_v2.md
    SS9 — no Celery/Redis). Opens its *own* session from `session_factory`
    rather than reusing the upload request's session: Starlette runs
    background tasks only after the response has been sent, by which point
    the request's `Depends(get_db)` session is already closed (see
    `db.session.get_session_factory`'s docstring).

    Never lets an exception escape (this runs outside any request context
    with nothing to report an unhandled exception to) — a failure here is
    recorded the same safe way every other stage failure is, via
    `ProcessingJob.stage`/`error_code`, by `run_analysis_pipeline` itself
    for ordinary processing failures; only a truly unexpected error
    (e.g. a DB connectivity failure) reaches the `except` below, and even
    then only its type, never its message, is logged. That `except` also
    marks the job FAILED itself (best-effort, in a fresh transaction) —
    without this, an unexpected mid-stage exception would leave `job.stage`
    frozen at whatever the last successful flush left it, so `GET .../status`
    would poll a stage that can never advance instead of a predictable
    terminal failure (Phase 8 spec: "API must respond predictably").
    """
    session = session_factory()
    try:
        run_analysis_pipeline(
            session,
            document_id,
            settings=settings,
            embedding_service=embedding_service,
            vector_store=vector_store,
            llm_client=llm_client,
        )
        session.commit()
    except Exception as exc:
        session.rollback()
        log_event(
            logger,
            "pipeline_background_task_failed",
            document_id=str(document_id),
            stage="failed",
            error_category=type(exc).__name__,
        )
        try:
            job = session.scalars(
                select(db_models.ProcessingJob).where(db_models.ProcessingJob.document_id == document_id)
            ).one_or_none()
            if job is not None and job.stage != ProcessingStage.COMPLETED:
                job.stage = ProcessingStage.FAILED
                job.error_code = ErrorCode.INTERNAL_ERROR.value
                job.completed_at = datetime.now(UTC)
                session.commit()
        except Exception:
            session.rollback()
    finally:
        session.close()
