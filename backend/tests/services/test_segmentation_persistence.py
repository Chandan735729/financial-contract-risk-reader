"""Clause persistence tests — Phase 3 spec SS16.

Uses the real `Clause`/`ProcessingJob` SQLAlchemy models (Phase 0/1 schema) —
no second clause table, no schema changes.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import db_models
from app.services.parsing.models import ParsedDocument
from app.services.parsing.pdf_parser import parse_pdf
from app.services.segmentation_service import persist_clauses, segment_document
from tests.conftest import make_document
from tests.fixtures.segmentation_documents import build_pdf_paragraphs


def _segment(paragraphs):
    data = build_pdf_paragraphs(paragraphs)
    parsed = parse_pdf(data, max_pages=200, min_text_chars=1, min_avg_chars_per_page=1.0).document
    assert parsed is not None
    return segment_document(parsed)


def test_persist_clauses_creates_sequential_rows_with_document_relation(db_session: Session):
    doc = make_document()
    db_session.add(doc)
    db_session.flush()

    result = _segment(
        [
            "1. Prepayment. Borrower may prepay subject to a 2% fee.",
            "2. Default. A missed payment is a default.",
        ]
    )
    rows = persist_clauses(db_session, doc.id, result)
    db_session.commit()

    assert len(rows) == 2
    persisted = db_session.scalars(
        select(db_models.Clause)
        .where(db_models.Clause.document_id == doc.id)
        .order_by(db_models.Clause.clause_index)
    ).all()
    assert [c.clause_index for c in persisted] == [0, 1]
    assert all(c.document_id == doc.id for c in persisted)
    assert persisted[0].raw_text.startswith("1. Prepayment")
    assert persisted[0].segmentation_confidence is not None
    assert persisted[0].low_confidence_flag is False


def test_persist_clauses_advances_processing_job_to_understanding(db_session: Session):
    doc = make_document()
    job = db_models.ProcessingJob(
        id=uuid.uuid4(), document_id=doc.id, stage=db_models.ProcessingStage.SEGMENTING
    )
    db_session.add_all([doc, job])
    db_session.flush()

    result = _segment(["1. A single clause."])
    persist_clauses(db_session, doc.id, result)
    db_session.commit()

    db_session.refresh(job)
    assert job.stage == db_models.ProcessingStage.UNDERSTANDING
    assert job.error_code is None


def test_persist_clauses_marks_job_failed_when_no_clauses_produced(db_session: Session):
    doc = make_document()
    job = db_models.ProcessingJob(
        id=uuid.uuid4(), document_id=doc.id, stage=db_models.ProcessingStage.SEGMENTING
    )
    db_session.add_all([doc, job])
    db_session.flush()

    result = segment_document(ParsedDocument(source_type="pdf", blocks=()))
    rows = persist_clauses(db_session, doc.id, result)
    db_session.commit()

    assert rows == []
    db_session.refresh(job)
    assert job.stage == db_models.ProcessingStage.FAILED
    assert job.error_code == "segmentation_low_confidence"


def test_deleting_document_cascades_to_persisted_clauses(db_session: Session):
    doc = make_document()
    db_session.add(doc)
    db_session.flush()

    result = _segment(["1. A clause that will be cascade-deleted."])
    rows = persist_clauses(db_session, doc.id, result)
    db_session.commit()
    clause_id = rows[0].id

    db_session.delete(doc)
    db_session.commit()

    assert db_session.get(db_models.Clause, clause_id) is None


def test_no_partial_clause_set_left_on_flush_failure(db_session: Session):
    # persist_clauses' own `db.flush()` call flushes the *entire* pending
    # session, not just its own rows — so a conflict from anything else
    # pending in the same transaction still proves the invariant: if flush
    # fails, nothing from that transaction (including persist_clauses'
    # freshly-added clauses) survives a rollback (Phase 3 spec SS16: "Do not
    # leave partially written clause sets").
    doc = make_document()
    db_session.add(doc)
    db_session.flush()

    dup_id = uuid.uuid4()
    db_session.add(
        db_models.Clause(id=dup_id, document_id=doc.id, clause_index=0, raw_text="pre-existing clause")
    )
    db_session.flush()
    # A second, not-yet-flushed row reusing the same primary key — this is
    # what makes persist_clauses' internal flush() fail.
    db_session.add(db_models.Clause(id=dup_id, document_id=doc.id, clause_index=1, raw_text="conflict"))

    result = _segment(["1. First.", "2. Second."])
    with pytest.raises(IntegrityError):
        persist_clauses(db_session, doc.id, result)
    db_session.rollback()

    # Rollback undoes the *whole* transaction, including the earlier
    # flush() of the pre-existing row — nothing from this transaction,
    # partial or otherwise, survives.
    surviving = db_session.scalars(
        select(db_models.Clause).where(db_models.Clause.document_id == doc.id)
    ).all()
    assert surviving == []
