"""Pipeline failure-path tests — Phase 8 spec's explicit failure-test list.

Covers the orchestrator-level failure/isolation behaviors that the
per-service test suites don't exercise together: a document-level parse
failure, segmentation producing zero clauses, a clause-level understanding
failure that must not take down the rest of the document, retrieval
returning no matches, a Risk Engine UNKNOWN result, a generation failure
from a missing LLM client, an unexpected mid-pipeline exception, and job
idempotency on a repeat call. Authorization failure paths (wrong/missing/
guessed token, not-found document) live in `test_document_authorization.py`.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select

from app.core.config import Settings
from app.models import db_models
from app.models.enums import (
    DocumentType,
    ErrorCode,
    ProcessingStage,
    RiskLevel,
)
from app.pipeline import analysis_pipeline
from app.services import storage
from tests.fixtures.synthetic_documents import build_corrupted_pdf, build_docx


def _make_document_and_job(db_session, settings: Settings, *, storage_path: str, file_format: str):
    document_id = uuid.uuid4()
    document = db_models.Document(
        id=document_id,
        access_token=uuid.uuid4().hex + uuid.uuid4().hex,
        storage_path=storage_path,
        file_format=file_format,
        document_type=DocumentType.UNKNOWN,
    )
    job = db_models.ProcessingJob(
        id=uuid.uuid4(),
        document_id=document_id,
        stage=ProcessingStage.SEGMENTING,
        started_at=datetime.now(UTC),
    )
    db_session.add(document)
    db_session.add(job)
    db_session.flush()
    return document, job


class TestParseFailure:
    def test_unparseable_stored_file_marks_job_failed(
        self, db_session, tmp_path, embedding_service, vector_store
    ):
        settings = Settings(
            environment="test",
            database_url="sqlite:///:memory:",
            upload_dir=str(tmp_path / "uploads"),
            min_text_chars=10,
            min_avg_chars_per_page=1.0,
        )
        storage_path = storage.save_document_file(
            settings.upload_dir, uuid.uuid4(), "pdf", build_corrupted_pdf()
        )
        document, job = _make_document_and_job(
            db_session, settings, storage_path=storage_path, file_format="pdf"
        )

        outcome = analysis_pipeline.run_analysis_pipeline(
            db_session,
            document.id,
            settings=settings,
            embedding_service=embedding_service,
            vector_store=vector_store,
        )

        assert outcome.final_stage == ProcessingStage.FAILED
        assert outcome.error_code is not None
        assert job.stage == ProcessingStage.FAILED
        assert job.error_code is not None
        # No clause is ever persisted for a document-level parse failure.
        assert (
            db_session.scalars(
                select(db_models.Clause).where(db_models.Clause.document_id == document.id)
            ).first()
            is None
        )

    def test_missing_storage_file_marks_job_failed_internal_error(
        self, db_session, tmp_path, embedding_service, vector_store
    ):
        settings = Settings(
            environment="test",
            database_url="sqlite:///:memory:",
            upload_dir=str(tmp_path / "uploads"),
            min_text_chars=10,
            min_avg_chars_per_page=1.0,
        )
        document, job = _make_document_and_job(
            db_session, settings, storage_path="does-not-exist.pdf", file_format="pdf"
        )

        outcome = analysis_pipeline.run_analysis_pipeline(
            db_session,
            document.id,
            settings=settings,
            embedding_service=embedding_service,
            vector_store=vector_store,
        )

        assert outcome.final_stage == ProcessingStage.FAILED
        assert outcome.error_code == ErrorCode.INTERNAL_ERROR.value


class TestSegmentationLowConfidence:
    def test_zero_clause_segmentation_marks_job_failed(
        self, db_session, tmp_path, embedding_service, vector_store, monkeypatch
    ):
        settings = Settings(
            environment="test",
            database_url="sqlite:///:memory:",
            upload_dir=str(tmp_path / "uploads"),
            min_text_chars=10,
            min_avg_chars_per_page=1.0,
        )
        storage_path = storage.save_document_file(
            settings.upload_dir,
            uuid.uuid4(),
            "docx",
            build_docx(items=[("Normal", "A single ordinary clause with enough text to parse cleanly.")]),
        )
        document, job = _make_document_and_job(
            db_session, settings, storage_path=storage_path, file_format="docx"
        )

        from app.services.segmentation_models import SegmentationDiagnostics, SegmentationResult
        from app.services.segmentation_service import segment_document as real_segment_document

        def _force_zero_clauses(parsed):
            real_segment_document(parsed)  # sanity: real parse/segment succeeds first
            return SegmentationResult(
                clauses=(),
                low_confidence_flag=True,
                diagnostics=SegmentationDiagnostics(
                    total_blocks=0,
                    suppressed_block_count=0,
                    heading_block_count=0,
                    total_chars=0,
                    suppressed_chars=0,
                    heading_metadata_chars=0,
                    covered_chars=0,
                    document_level_anomaly="forced_zero_for_test",
                ),
            )

        monkeypatch.setattr(analysis_pipeline.segmentation_service, "segment_document", _force_zero_clauses)

        outcome = analysis_pipeline.run_analysis_pipeline(
            db_session,
            document.id,
            settings=settings,
            embedding_service=embedding_service,
            vector_store=vector_store,
        )

        assert outcome.final_stage == ProcessingStage.FAILED
        assert outcome.error_code == ErrorCode.SEGMENTATION_LOW_CONFIDENCE.value
        assert job.stage == ProcessingStage.FAILED


class TestClauseLevelIsolation:
    def test_one_clause_understanding_failure_does_not_take_down_the_document(
        self, db_session, tmp_path, embedding_service, vector_store, monkeypatch
    ):
        """Entity/condition/retrieval extraction failure for one clause
        (Phase 8 spec: "entity extraction failure", "condition extraction
        failure", "partial clause failure") must not prevent the rest of
        the document from reaching COMPLETED."""
        settings = Settings(
            environment="test",
            database_url="sqlite:///:memory:",
            upload_dir=str(tmp_path / "uploads"),
            min_text_chars=10,
            min_avg_chars_per_page=1.0,
        )
        storage_path = storage.save_document_file(
            settings.upload_dir,
            uuid.uuid4(),
            "docx",
            build_docx(
                items=[
                    ("Heading 1", "1. Prepayment"),
                    ("Normal", "Borrower may prepay at any time without penalty."),
                    ("Heading 1", "2. Forced Failure"),
                    ("Normal", "This clause will be forced to fail understanding in the test."),
                ],
                include_table=False,
            ),
        )
        document, job = _make_document_and_job(
            db_session, settings, storage_path=storage_path, file_format="docx"
        )

        from app.services.clause_understanding_service import (
            run_clause_understanding as real_run_clause_understanding,
        )

        def _maybe_fail(db, clause, **kwargs):
            if "forced to fail" in clause.raw_text:
                raise RuntimeError("synthetic clause-understanding failure for test")
            return real_run_clause_understanding(db, clause, **kwargs)

        monkeypatch.setattr(analysis_pipeline, "run_clause_understanding", _maybe_fail)

        outcome = analysis_pipeline.run_analysis_pipeline(
            db_session,
            document.id,
            settings=settings,
            embedding_service=embedding_service,
            vector_store=vector_store,
        )

        assert outcome.final_stage == ProcessingStage.COMPLETED
        assert outcome.understanding_failed == 1
        assert outcome.clause_count == 2

        clauses = db_session.scalars(
            select(db_models.Clause)
            .where(db_models.Clause.document_id == document.id)
            .order_by(db_models.Clause.clause_index)
        ).all()
        assert len(clauses) == 2
        ok_clause, failed_clause = clauses[0], clauses[1]
        assert ok_clause.analyses and ok_clause.analyses[0].risk_level == RiskLevel.LOW
        # The failed clause's SAVEPOINT rolled back entirely -- no analysis
        # row at all, which score_document/generate_pending_explanations
        # already treat as a safe "skipped_unanalyzed" state.
        assert failed_clause.analyses == []


class TestRetrievalNoMatchAndUnknown:
    def test_empty_corpus_and_ambiguous_clause_abstain_without_crashing(
        self, db_session, tmp_path, embedding_service, vector_store
    ):
        settings = Settings(
            environment="test",
            database_url="sqlite:///:memory:",
            upload_dir=str(tmp_path / "uploads"),
            min_text_chars=10,
            min_avg_chars_per_page=1.0,
        )
        storage_path = storage.save_document_file(
            settings.upload_dir,
            uuid.uuid4(),
            "docx",
            build_docx(items=[("Normal", "Prepayment provisions may apply under certain circumstances.")]),
        )
        document, job = _make_document_and_job(
            db_session, settings, storage_path=storage_path, file_format="docx"
        )

        outcome = analysis_pipeline.run_analysis_pipeline(
            db_session,
            document.id,
            settings=settings,
            embedding_service=embedding_service,
            vector_store=vector_store,
        )

        assert outcome.final_stage == ProcessingStage.COMPLETED
        analysis = db_session.scalars(select(db_models.ClauseAnalysisORM)).one()
        assert analysis.risk_level == RiskLevel.UNKNOWN
        assert analysis.abstained is True
        assert analysis.matched_patterns == []  # empty vector store -- genuine no-match, not a crash


class TestGenerationFailureNoClient:
    def test_missing_llm_client_falls_back_without_failing_the_document(
        self, db_session, tmp_path, embedding_service, vector_store
    ):
        """No `anthropic_api_key` configured (default test settings) and no
        fake client injected -- `build_llm_client` raises, and every
        eligible clause safely falls back rather than failing the job."""
        settings = Settings(
            environment="test",
            database_url="sqlite:///:memory:",
            upload_dir=str(tmp_path / "uploads"),
            min_text_chars=10,
            min_avg_chars_per_page=1.0,
        )
        storage_path = storage.save_document_file(
            settings.upload_dir,
            uuid.uuid4(),
            "docx",
            build_docx(
                items=[
                    ("Heading 1", "1. Prepayment"),
                    (
                        "Normal",
                        "Borrower shall pay a prepayment penalty equal to 5% of the outstanding "
                        "principal if the loan is repaid in full within 24 months of disbursement.",
                    ),
                    # A second clause avoids segmentation's own
                    # "single_clause_dominates_document" low-confidence
                    # anomaly (one clause covering 100% of the document is
                    # itself a document-level low-confidence signal,
                    # unrelated to what this test wants to isolate).
                    ("Heading 1", "2. Prepayment Rights"),
                    ("Normal", "Borrower may prepay at any time without penalty."),
                ],
                include_table=False,
            ),
        )
        document, job = _make_document_and_job(
            db_session, settings, storage_path=storage_path, file_format="docx"
        )

        outcome = analysis_pipeline.run_analysis_pipeline(
            db_session,
            document.id,
            settings=settings,
            embedding_service=embedding_service,
            vector_store=vector_store,
            llm_client=None,
        )

        assert outcome.final_stage == ProcessingStage.COMPLETED
        analyses = {a.risk_level: a for a in db_session.scalars(select(db_models.ClauseAnalysisORM)).all()}
        high = analyses[RiskLevel.HIGH]
        assert high.explanation is None
        assert high.explanation_grounded is False
        low = analyses[RiskLevel.LOW]
        assert low.explanation is None
        assert low.explanation_grounded is None  # ineligible risk level, generation never attempted


class TestUnexpectedFailureIsPredictable:
    def test_unexpected_exception_leaves_job_failed_not_stuck(
        self, db_session, engine, tmp_path, embedding_service, vector_store, monkeypatch
    ):
        from sqlalchemy.orm import sessionmaker as sessionmaker_factory

        from app.db.session import create_session_factory

        settings = Settings(
            environment="test",
            database_url="sqlite:///:memory:",
            upload_dir=str(tmp_path / "uploads"),
            min_text_chars=10,
            min_avg_chars_per_page=1.0,
        )
        storage_path = storage.save_document_file(
            settings.upload_dir,
            uuid.uuid4(),
            "docx",
            build_docx(items=[("Normal", "Borrower may prepay at any time without penalty.")]),
        )
        document, job = _make_document_and_job(
            db_session, settings, storage_path=storage_path, file_format="docx"
        )
        db_session.commit()

        def _boom(*args, **kwargs):
            raise RuntimeError("synthetic unexpected failure")

        monkeypatch.setattr(analysis_pipeline, "score_document", _boom)

        session_factory: sessionmaker_factory = create_session_factory(engine)
        analysis_pipeline.run_analysis_pipeline_in_background(
            session_factory,
            document.id,
            settings=settings,
            embedding_service=embedding_service,
            vector_store=vector_store,
        )

        refreshed = db_session.scalars(
            select(db_models.ProcessingJob).where(db_models.ProcessingJob.document_id == document.id)
        ).one()
        assert refreshed.stage == ProcessingStage.FAILED
        assert refreshed.error_code == ErrorCode.INTERNAL_ERROR.value


class TestJobIdempotency:
    def test_repeat_call_on_completed_job_does_not_duplicate_rows(
        self, db_session, tmp_path, embedding_service, vector_store
    ):
        settings = Settings(
            environment="test",
            database_url="sqlite:///:memory:",
            upload_dir=str(tmp_path / "uploads"),
            min_text_chars=10,
            min_avg_chars_per_page=1.0,
        )
        storage_path = storage.save_document_file(
            settings.upload_dir,
            uuid.uuid4(),
            "docx",
            build_docx(items=[("Normal", "Borrower may prepay at any time without penalty.")]),
        )
        document, job = _make_document_and_job(
            db_session, settings, storage_path=storage_path, file_format="docx"
        )

        first = analysis_pipeline.run_analysis_pipeline(
            db_session,
            document.id,
            settings=settings,
            embedding_service=embedding_service,
            vector_store=vector_store,
        )
        assert first.final_stage == ProcessingStage.COMPLETED

        second = analysis_pipeline.run_analysis_pipeline(
            db_session,
            document.id,
            settings=settings,
            embedding_service=embedding_service,
            vector_store=vector_store,
        )
        assert second.final_stage == ProcessingStage.COMPLETED

        clauses = db_session.scalars(
            select(db_models.Clause).where(db_models.Clause.document_id == document.id)
        ).all()
        assert len(clauses) == 1
        analyses = db_session.scalars(select(db_models.ClauseAnalysisORM)).all()
        assert len(analyses) == 1
