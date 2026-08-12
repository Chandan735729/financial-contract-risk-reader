"""Financial entity persistence tests — Phase 4 spec SS21.

Uses the real `financial_entities`/`evidence_spans` schema (Phase 0/1) — no
new table.
"""

from __future__ import annotations

from sqlalchemy import select

from app.models import db_models
from app.services.entity_extraction_service import extract_financial_entities, persist_entities
from tests.conftest import make_clause, make_clause_analysis, make_document


def _make_analysis(db_session):
    doc = make_document()
    clause = make_clause(document_id=doc.id, raw_text="placeholder")
    analysis = make_clause_analysis(clause_id=clause.id)
    db_session.add_all([doc, clause, analysis])
    db_session.flush()
    return analysis


def test_persist_entities_creates_financial_entity_rows(db_session):
    analysis = _make_analysis(db_session)
    entities = extract_financial_entities("Borrower shall pay a prepayment penalty of 2% within 30 days.")

    rows = persist_entities(db_session, analysis.id, entities)
    db_session.commit()

    assert len(rows) == len(entities) == 2
    persisted = db_session.scalars(
        select(db_models.FinancialEntity).where(db_models.FinancialEntity.clause_analysis_id == analysis.id)
    ).all()
    assert len(persisted) == 2
    types = {row.entity_type for row in persisted}
    assert types == {"percentage", "time_period"}


def test_persist_entities_creates_unverified_evidence_span_per_entity(db_session):
    analysis = _make_analysis(db_session)
    entities = extract_financial_entities("A fee of 5% applies.")

    persist_entities(db_session, analysis.id, entities)
    db_session.commit()

    spans = db_session.scalars(
        select(db_models.EvidenceSpan).where(db_models.EvidenceSpan.clause_analysis_id == analysis.id)
    ).all()
    assert len(spans) == 1
    assert spans[0].verified is False
    assert spans[0].text == "5%"

    entity = db_session.scalars(
        select(db_models.FinancialEntity).where(db_models.FinancialEntity.clause_analysis_id == analysis.id)
    ).one()
    assert entity.evidence_span_id == spans[0].id


def test_persist_entities_with_no_entities_creates_nothing(db_session):
    analysis = _make_analysis(db_session)
    rows = persist_entities(db_session, analysis.id, [])
    db_session.commit()
    assert rows == []


def test_deleting_clause_analysis_cascades_financial_entities_and_spans(db_session):
    analysis = _make_analysis(db_session)
    entities = extract_financial_entities("A fee of 5% applies within 30 days.")
    persist_entities(db_session, analysis.id, entities)
    db_session.commit()

    analysis_id = analysis.id
    db_session.delete(analysis)
    db_session.commit()

    remaining_entities = db_session.scalars(
        select(db_models.FinancialEntity).where(db_models.FinancialEntity.clause_analysis_id == analysis_id)
    ).all()
    remaining_spans = db_session.scalars(
        select(db_models.EvidenceSpan).where(db_models.EvidenceSpan.clause_analysis_id == analysis_id)
    ).all()
    assert remaining_entities == []
    assert remaining_spans == []


def test_raw_text_exact_substring_preserved_end_to_end(db_session):
    analysis = _make_analysis(db_session)
    text = "Interest accrues at 18% p.a. on any overdue balance exceeding Rs. 10,000."
    entities = extract_financial_entities(text)
    persist_entities(db_session, analysis.id, entities)
    db_session.commit()

    persisted = db_session.scalars(
        select(db_models.FinancialEntity).where(db_models.FinancialEntity.clause_analysis_id == analysis.id)
    ).all()
    for row in persisted:
        assert row.raw_text in text
