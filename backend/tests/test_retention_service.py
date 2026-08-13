"""Automatic retention cleanup — Phase 11, Security_and_Privacy_v2.md SS3.
Verifies: expired-document deletion, derived-data deletion (full cascade),
storage-file deletion, corpus preservation, active-document preservation,
and idempotency on repeated runs.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.models import db_models
from app.services import storage
from app.services.retention_service import run_retention_cleanup
from tests.conftest import make_clause, make_clause_analysis, make_corpus_pattern, make_document


def _make_document(db_session, *, created_at: datetime, token: str) -> db_models.Document:
    document = make_document(access_token=token, created_at=created_at)
    db_session.add(document)
    db_session.flush()

    clause = make_clause(document.id, raw_text="Borrower shall pay a 5% prepayment penalty.")
    db_session.add(clause)
    db_session.flush()

    analysis = make_clause_analysis(clause.id, risk_level=db_models.RiskLevel.HIGH, risk_score=0.8)
    db_session.add(analysis)
    db_session.flush()

    return document


class TestRetentionCleanup:
    def test_deletes_a_document_older_than_the_retention_window(self, db_session):
        now = datetime.now(UTC)
        old_document = _make_document(db_session, created_at=now - timedelta(days=100), token="a" * 64)
        db_session.commit()

        summary = run_retention_cleanup(db_session, retention_days=90, upload_dir="/nonexistent", now=now)
        db_session.commit()

        assert summary.deleted == 1
        assert summary.failed == 0
        assert db_session.get(db_models.Document, old_document.id) is None

    def test_preserves_a_document_within_the_retention_window(self, db_session):
        now = datetime.now(UTC)
        recent_document = _make_document(db_session, created_at=now - timedelta(days=10), token="b" * 64)
        db_session.commit()

        summary = run_retention_cleanup(db_session, retention_days=90, upload_dir="/nonexistent", now=now)
        db_session.commit()

        assert summary.deleted == 0
        assert summary.candidates == 0
        assert db_session.get(db_models.Document, recent_document.id) is not None

    def test_deletes_derived_data_but_preserves_corpus_data(self, db_session):
        now = datetime.now(UTC)
        document = _make_document(db_session, created_at=now - timedelta(days=200), token="c" * 64)
        clause = db_session.query(db_models.Clause).filter_by(document_id=document.id).one()
        analysis = db_session.query(db_models.ClauseAnalysisORM).filter_by(clause_id=clause.id).one()

        corpus_pattern = make_corpus_pattern()
        db_session.add(corpus_pattern)
        db_session.flush()
        matched = db_models.MatchedPattern(
            id=uuid.uuid4(),
            clause_analysis_id=analysis.id,
            corpus_pattern_id=corpus_pattern.id,
            similarity_score=0.9,
            lexical_score=0.5,
        )
        db_session.add(matched)
        db_session.commit()

        run_retention_cleanup(db_session, retention_days=90, upload_dir="/nonexistent", now=now)
        db_session.commit()

        assert db_session.get(db_models.Clause, clause.id) is None
        assert db_session.get(db_models.ClauseAnalysisORM, analysis.id) is None
        assert db_session.get(db_models.MatchedPattern, matched.id) is None
        assert db_session.get(db_models.CorpusPattern, corpus_pattern.id) is not None

    def test_deletes_the_stored_file(self, db_session, tmp_path):
        upload_dir = str(tmp_path / "uploads")
        now = datetime.now(UTC)
        document = make_document(access_token="d" * 64, created_at=now - timedelta(days=200))
        db_session.add(document)
        db_session.flush()
        storage_filename = storage.save_document_file(upload_dir, document.id, "pdf", b"%PDF-1.7 fake")
        document.storage_path = storage_filename
        db_session.commit()

        stored_file = Path(upload_dir) / storage_filename
        assert stored_file.exists()

        run_retention_cleanup(db_session, retention_days=90, upload_dir=upload_dir, now=now)
        db_session.commit()

        assert not stored_file.exists()

    def test_repeated_cleanup_is_idempotent(self, db_session):
        now = datetime.now(UTC)
        _make_document(db_session, created_at=now - timedelta(days=200), token="e" * 64)
        db_session.commit()

        first = run_retention_cleanup(db_session, retention_days=90, upload_dir="/nonexistent", now=now)
        db_session.commit()
        second = run_retention_cleanup(db_session, retention_days=90, upload_dir="/nonexistent", now=now)
        db_session.commit()

        assert first.deleted == 1
        assert second.deleted == 0
        assert second.candidates == 0
        assert second.failed == 0

    def test_mixed_batch_only_deletes_expired_documents(self, db_session):
        now = datetime.now(UTC)
        old_document = _make_document(db_session, created_at=now - timedelta(days=91), token="f" * 64)
        recent_document = _make_document(db_session, created_at=now - timedelta(days=1), token="g" * 64)
        db_session.commit()

        summary = run_retention_cleanup(db_session, retention_days=90, upload_dir="/nonexistent", now=now)
        db_session.commit()

        assert summary.deleted == 1
        assert db_session.get(db_models.Document, old_document.id) is None
        assert db_session.get(db_models.Document, recent_document.id) is not None
