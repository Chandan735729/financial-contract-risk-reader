"""Performance/reliability smoke test — Phase 10 security audit SS18.

Explicitly NOT a real load test (no concurrency, no external load-generation
tool, no public target) — a small, controlled, in-process sequential run
sufficient to catch the specific failure classes SS18 asks about: request
crashes, obvious leaks (temp files, DB rows), and repeated-job duplication.
A genuine concurrent/soak load test needs infrastructure this repo
deliberately doesn't have yet (Technical_Architecture_v2.md SS9's
single-worker MVP design) — see docs/SECURITY_AUDIT.md for the documented
limitation and what a real load test would need.
"""

from __future__ import annotations

from pathlib import Path

from app.models import db_models
from app.models.enums import ProcessingStage
from tests.fixtures.synthetic_documents import build_docx


def _upload(client, pdf_bytes: bytes, name: str):
    return client.post(
        "/v1/documents",
        files={
            "file": (
                name,
                pdf_bytes,
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        },
    )


class TestSmokeLoad:
    def test_sequential_uploads_complete_cleanly_with_no_leaks_or_duplication(
        self, make_client, db_session, tmp_path
    ):
        # A generous rate-limit override -- this test is about pipeline
        # reliability under repeated use, not re-proving rate limiting
        # (already covered by test_upload_rate_limit.py).
        client = make_client(
            upload_rate_limit_max_requests=100, min_text_chars=10, min_avg_chars_per_page=1.0
        )

        iterations = 15
        document_ids: list[str] = []
        doc_bytes = build_docx(
            items=[
                ("Heading 1", "1. Prepayment"),
                (
                    "Normal",
                    "Borrower shall pay a prepayment penalty equal to 5% of the outstanding "
                    "principal if the loan is repaid within 24 months.",
                ),
            ],
            include_table=False,
        )

        for i in range(iterations):
            response = _upload(client, doc_bytes, f"contract-{i}.docx")
            assert response.status_code == 201, response.text
            document_ids.append(response.json()["document_id"])

        # No crashes across the run, and every job actually reached a
        # terminal state (never stuck mid-pipeline) -- the background
        # pipeline task runs synchronously under TestClient, so this is
        # already true by the time the loop above returns, but assert it
        # explicitly rather than assuming.
        jobs = db_session.query(db_models.ProcessingJob).all()
        assert len(jobs) == iterations
        for job in jobs:
            assert job.stage in (ProcessingStage.COMPLETED, ProcessingStage.FAILED)

        # No duplicated rows from a repeated/re-entrant job (Phase 8's
        # idempotency design) -- one clause per document, one analysis per
        # clause, for this fixture.
        clauses = db_session.query(db_models.Clause).all()
        assert len(clauses) == iterations
        analyses = db_session.query(db_models.ClauseAnalysisORM).all()
        assert len(analyses) == iterations

        # No leftover .tmp files from storage.save_document_file's
        # write-then-atomic-rename pattern.
        upload_dir = Path(tmp_path) / "uploads"
        leftover_tmp_files = list(upload_dir.glob("*.tmp"))
        assert leftover_tmp_files == []

        # One real file per document, matching document_id.<ext> naming --
        # no orphaned or missing files.
        stored_files = {p.stem for p in upload_dir.glob("*") if p.is_file()}
        assert stored_files == set(document_ids)

    def test_repeat_pipeline_call_on_the_same_document_does_not_duplicate_rows(
        self, make_client, db_session, tmp_path, embedding_service, vector_store
    ):
        """A second, direct call to the pipeline for an already-COMPLETED
        document (simulating a retried/duplicate background-task trigger)
        must be a no-op, not a duplicate insert -- covers the same
        `run_analysis_pipeline` idempotency Phase 8 already tested at the
        unit level, exercised here through the full HTTP upload path."""
        import uuid

        from app.core.config import Settings
        from app.pipeline.analysis_pipeline import run_analysis_pipeline

        client = make_client(min_text_chars=10, min_avg_chars_per_page=1.0)
        doc_bytes = build_docx(items=[("Normal", "Borrower may prepay at any time without penalty.")])
        response = _upload(client, doc_bytes, "contract.docx")
        assert response.status_code == 201
        document_id = uuid.UUID(response.json()["document_id"])

        settings = Settings(
            environment="test", database_url="sqlite:///:memory:", upload_dir=str(tmp_path / "uploads")
        )

        outcome = run_analysis_pipeline(
            db_session,
            document_id,
            settings=settings,
            embedding_service=embedding_service,
            vector_store=vector_store,
        )
        assert outcome.final_stage == ProcessingStage.COMPLETED

        clauses = db_session.query(db_models.Clause).filter_by(document_id=document_id).all()
        assert len(clauses) == 1
