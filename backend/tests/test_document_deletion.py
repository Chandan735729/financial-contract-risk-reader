"""`DELETE /v1/documents/{id}` — Phase 10 security audit,
Security_and_Privacy_v2.md SS3 ("Documents and all derived data ... are
deletable by the access-token holder on request"). Verifies the
authorization gate, the full cascade (clauses, analyses, evidence spans,
financial entities, matched patterns), that the stored file is removed,
and — critically — that permanent corpus/reference data is never reachable
through this operation.
"""

from __future__ import annotations

import uuid

from app.models import db_models
from app.services import storage
from tests.conftest import make_clause, make_clause_analysis, make_corpus_pattern, make_document

_DELETE_HEADERS = lambda token: {"Authorization": f"Bearer {token}"}  # noqa: E731


def _make_full_document(db_session):
    """A document with one clause, one analysis, one verified evidence
    span, one financial entity, and one matched pattern against a
    permanent corpus pattern -- the full fan-out DELETE must clean up
    (except the corpus pattern itself)."""
    document = make_document(access_token="d" * 64)
    db_session.add(document)
    db_session.flush()

    clause = make_clause(document.id, raw_text="Borrower shall pay a 5% prepayment penalty.")
    db_session.add(clause)
    db_session.flush()

    analysis = make_clause_analysis(clause.id, risk_level=db_models.RiskLevel.HIGH, risk_score=0.8)
    db_session.add(analysis)
    db_session.flush()

    span = db_models.EvidenceSpan(
        id=uuid.uuid4(),
        clause_analysis_id=analysis.id,
        text="5% prepayment penalty",
        start_char=0,
        end_char=22,
        verified=True,
    )
    db_session.add(span)
    db_session.flush()

    entity = db_models.FinancialEntity(
        id=uuid.uuid4(),
        clause_analysis_id=analysis.id,
        entity_type="percentage",
        value="5",
        unit="%",
        raw_text="5%",
        evidence_span_id=span.id,
    )
    db_session.add(entity)

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
    db_session.flush()

    return document, clause, analysis, span, entity, corpus_pattern, matched


class TestDocumentDeletion:
    def test_correct_token_deletes_document_and_all_derived_data(self, make_client, db_session, tmp_path):
        client = make_client()
        document, clause, analysis, span, entity, corpus_pattern, matched = _make_full_document(db_session)
        db_session.commit()

        response = client.delete(
            f"/v1/documents/{document.id}", headers=_DELETE_HEADERS(document.access_token)
        )
        assert response.status_code == 204

        assert db_session.get(db_models.Document, document.id) is None
        assert db_session.get(db_models.Clause, clause.id) is None
        assert db_session.get(db_models.ClauseAnalysisORM, analysis.id) is None
        assert db_session.get(db_models.EvidenceSpan, span.id) is None
        assert db_session.get(db_models.FinancialEntity, entity.id) is None
        assert db_session.get(db_models.MatchedPattern, matched.id) is None

        # Permanent corpus/reference data must survive a user-facing delete.
        assert db_session.get(db_models.CorpusPattern, corpus_pattern.id) is not None

    def test_deletion_removes_the_stored_file(self, make_client, db_session, tmp_path):
        upload_dir = str(tmp_path / "uploads")
        client = make_client()
        document = make_document(access_token="e" * 64, storage_path=None)
        db_session.add(document)
        db_session.flush()
        storage_filename = storage.save_document_file(upload_dir, document.id, "pdf", b"%PDF-1.7 fake")
        document.storage_path = storage_filename
        db_session.commit()

        from pathlib import Path

        stored_file = Path(upload_dir) / storage_filename
        assert stored_file.exists()

        response = client.delete(
            f"/v1/documents/{document.id}", headers=_DELETE_HEADERS(document.access_token)
        )
        assert response.status_code == 204
        assert not stored_file.exists()

    def test_deleted_document_is_no_longer_readable(self, make_client, db_session, tmp_path):
        client = make_client()
        document, *_ = _make_full_document(db_session)
        db_session.add(
            db_models.ProcessingJob(
                id=uuid.uuid4(), document_id=document.id, stage=db_models.ProcessingStage.COMPLETED
            )
        )
        db_session.commit()

        client.delete(f"/v1/documents/{document.id}", headers=_DELETE_HEADERS(document.access_token))

        status_response = client.get(
            f"/v1/documents/{document.id}/status", headers=_DELETE_HEADERS(document.access_token)
        )
        assert status_response.status_code == 404
        assert status_response.json()["error"]["code"] == "access_denied"

    def test_wrong_token_cannot_delete(self, make_client, db_session, tmp_path):
        client = make_client()
        document, *_ = _make_full_document(db_session)
        db_session.commit()

        response = client.delete(f"/v1/documents/{document.id}", headers=_DELETE_HEADERS("x" * 64))
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "access_denied"
        assert db_session.get(db_models.Document, document.id) is not None

    def test_missing_token_cannot_delete(self, make_client, db_session, tmp_path):
        client = make_client()
        document, *_ = _make_full_document(db_session)
        db_session.commit()

        response = client.delete(f"/v1/documents/{document.id}")
        assert response.status_code == 404
        assert db_session.get(db_models.Document, document.id) is not None

    def test_nonexistent_document_returns_access_denied_not_a_crash(self, make_client, tmp_path):
        client = make_client()
        response = client.delete(f"/v1/documents/{uuid.uuid4()}", headers=_DELETE_HEADERS("y" * 64))
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "access_denied"

    def test_another_documents_token_cannot_delete(self, make_client, db_session, tmp_path):
        client = make_client()
        document, *_ = _make_full_document(db_session)
        other = make_document(access_token="f" * 64)
        db_session.add(other)
        db_session.commit()

        response = client.delete(f"/v1/documents/{document.id}", headers=_DELETE_HEADERS(other.access_token))
        assert response.status_code == 404
        assert db_session.get(db_models.Document, document.id) is not None
