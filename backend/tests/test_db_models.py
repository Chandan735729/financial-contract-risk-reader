"""SQLAlchemy model tests: UUID PKs, FK cascade behavior.

All text values are synthetic placeholders, never real contract language.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, StatementError
from sqlalchemy.orm import Session

from app.models import db_models
from tests.conftest import make_clause, make_clause_analysis, make_document


def test_document_uuid_pk_round_trips_as_uuid(db_session: Session):
    doc = make_document()
    db_session.add(doc)
    db_session.commit()
    db_session.refresh(doc)

    fetched = db_session.get(db_models.Document, doc.id)
    assert fetched is not None
    assert isinstance(fetched.id, uuid.UUID)
    assert fetched.id == doc.id


def test_access_token_unique_constraint(db_session: Session):
    token = uuid.uuid4().hex
    db_session.add(make_document(access_token=token))
    db_session.commit()

    db_session.add(make_document(access_token=token))
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_deleting_document_cascades_to_clauses_and_analyses(db_session: Session):
    doc = make_document()
    clause = make_clause(document_id=doc.id)
    doc.clauses.append(clause)
    analysis = make_clause_analysis(clause_id=clause.id)
    clause.analyses.append(analysis)

    db_session.add(doc)
    db_session.commit()

    clause_id = clause.id
    analysis_id = analysis.id

    db_session.delete(doc)
    db_session.commit()

    assert db_session.get(db_models.Clause, clause_id) is None
    assert db_session.get(db_models.ClauseAnalysisORM, analysis_id) is None


def test_deleting_clause_analysis_cascades_evidence_and_matched_patterns(db_session: Session):
    doc = make_document()
    clause = make_clause(document_id=doc.id)
    analysis = make_clause_analysis(clause_id=clause.id)
    doc.clauses.append(clause)
    clause.analyses.append(analysis)

    span = db_models.EvidenceSpan(
        id=uuid.uuid4(),
        clause_analysis_id=analysis.id,
        text="synthetic evidence excerpt",
        start_char=0,
        end_char=10,
        verified=True,
    )
    analysis.evidence_spans.append(span)

    pattern = db_models.CorpusPattern(
        id=uuid.uuid4(),
        pattern_text="synthetic corpus pattern",
        taxonomy_version="taxonomy_v1",
    )
    match = db_models.MatchedPattern(
        id=uuid.uuid4(),
        clause_analysis_id=analysis.id,
        corpus_pattern_id=pattern.id,
        similarity_score=0.8,
        lexical_score=0.5,
    )
    analysis.matched_patterns.append(match)

    db_session.add_all([doc, pattern])
    db_session.commit()

    span_id, match_id = span.id, match.id
    db_session.delete(analysis)
    db_session.commit()

    assert db_session.get(db_models.EvidenceSpan, span_id) is None
    assert db_session.get(db_models.MatchedPattern, match_id) is None
    # Corpus pattern itself is permanent reference data — not deleted.
    assert db_session.get(db_models.CorpusPattern, pattern.id) is not None


def test_deleting_evidence_span_nulls_financial_entity_link_not_cascade(db_session: Session):
    doc = make_document()
    clause = make_clause(document_id=doc.id)
    analysis = make_clause_analysis(clause_id=clause.id)
    doc.clauses.append(clause)
    clause.analyses.append(analysis)

    span = db_models.EvidenceSpan(
        id=uuid.uuid4(),
        clause_analysis_id=analysis.id,
        text="synthetic 5% fee mention",
        start_char=0,
        end_char=20,
        verified=True,
    )
    analysis.evidence_spans.append(span)

    entity = db_models.FinancialEntity(
        id=uuid.uuid4(),
        clause_analysis_id=analysis.id,
        entity_type="percentage",
        value="5",
        raw_text="5%",
        evidence_span_id=span.id,
    )
    analysis.financial_entities.append(entity)

    db_session.add(doc)
    db_session.commit()

    entity_id = entity.id
    db_session.delete(span)
    db_session.commit()

    fetched_entity = db_session.get(db_models.FinancialEntity, entity_id)
    assert fetched_entity is not None
    assert fetched_entity.evidence_span_id is None


def test_corpus_pattern_deletion_restricted_while_referenced(db_session: Session):
    doc = make_document()
    clause = make_clause(document_id=doc.id)
    analysis = make_clause_analysis(clause_id=clause.id)
    doc.clauses.append(clause)
    clause.analyses.append(analysis)

    pattern = db_models.CorpusPattern(
        id=uuid.uuid4(),
        pattern_text="synthetic corpus pattern",
        taxonomy_version="taxonomy_v1",
    )
    match = db_models.MatchedPattern(
        id=uuid.uuid4(),
        clause_analysis_id=analysis.id,
        corpus_pattern_id=pattern.id,
        similarity_score=0.9,
        lexical_score=0.4,
    )
    analysis.matched_patterns.append(match)

    db_session.add_all([doc, pattern])
    db_session.commit()

    db_session.delete(pattern)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_processing_job_defaults_to_queued(db_session: Session):
    doc = make_document()
    job = db_models.ProcessingJob(id=uuid.uuid4(), document_id=doc.id)
    doc.processing_jobs.append(job)
    db_session.add(doc)
    db_session.commit()

    fetched = db_session.scalars(select(db_models.ProcessingJob)).one()
    assert fetched.stage == db_models.ProcessingStage.QUEUED


def test_deleting_document_cascades_processing_jobs(db_session: Session):
    doc = make_document()
    job = db_models.ProcessingJob(id=uuid.uuid4(), document_id=doc.id)
    doc.processing_jobs.append(job)
    db_session.add(doc)
    db_session.commit()

    job_id = job.id
    db_session.delete(doc)
    db_session.commit()

    assert db_session.get(db_models.ProcessingJob, job_id) is None


def test_invalid_enum_value_rejected_at_db_layer(db_session: Session):
    # `_enum_column` uses `validate_strings=True` (db_models.py) precisely so
    # a bad string can't silently reach the database as a `document_type` —
    # this exercises that guard, not just the Python Enum constructor.
    doc = make_document(document_type="not_a_real_document_type")
    db_session.add(doc)
    with pytest.raises(StatementError, match="not among the defined enum values"):
        db_session.commit()
    db_session.rollback()


def test_user_deletion_sets_document_user_id_null(db_session: Session):
    user = db_models.User(id=uuid.uuid4(), email="synthetic-test-user@example.invalid")
    doc = make_document(user_id=user.id)
    db_session.add_all([user, doc])
    db_session.commit()

    db_session.delete(user)
    db_session.commit()

    db_session.refresh(doc)
    assert doc.user_id is None
