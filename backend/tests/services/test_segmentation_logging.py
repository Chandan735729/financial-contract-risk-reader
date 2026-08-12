"""Logging-safety tests for the segmentation pipeline — Phase 3 spec SS14.

Confirms `persist_clauses` never logs raw clause text (or anything derived
from it), only the same safe metadata allowlist the rest of the backend
uses (Security_and_Privacy_v2.md SS6).
"""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.core.logging import REDACTED_DISALLOWED
from app.services.parsing.pdf_parser import parse_pdf
from app.services.segmentation_service import persist_clauses, segment_document
from tests.conftest import make_document
from tests.fixtures.segmentation_documents import build_pdf_paragraphs

_SENSITIVE_CLAUSE_TEXT = "Synthetic borrower shall pay a confidential 2% prepayment fee under this agreement."


def test_persist_clauses_never_logs_raw_clause_text(db_session: Session, caplog):
    doc = make_document()
    db_session.add(doc)
    db_session.flush()

    data = build_pdf_paragraphs([f"1. Prepayment. {_SENSITIVE_CLAUSE_TEXT}"])
    parsed = parse_pdf(data, max_pages=200, min_text_chars=1, min_avg_chars_per_page=1.0).document
    assert parsed is not None
    result = segment_document(parsed)

    with caplog.at_level(logging.DEBUG):
        persist_clauses(db_session, doc.id, result)
    db_session.commit()

    log_text = "\n".join(record.getMessage() for record in caplog.records)
    log_text += "\n".join(str(getattr(record, "fields", "")) for record in caplog.records)

    assert _SENSITIVE_CLAUSE_TEXT not in log_text
    assert "Prepayment" not in log_text
    # section_heading content must not leak either, even though it's just a
    # short heading string, not full clause text.
    assert result.clauses[0].raw_text not in log_text


def test_persist_clauses_log_event_only_carries_allowlisted_fields(db_session: Session, caplog):
    doc = make_document()
    db_session.add(doc)
    db_session.flush()

    data = build_pdf_paragraphs([f"1. Prepayment. {_SENSITIVE_CLAUSE_TEXT}"])
    parsed = parse_pdf(data, max_pages=200, min_text_chars=1, min_avg_chars_per_page=1.0).document
    assert parsed is not None
    result = segment_document(parsed)

    with caplog.at_level(logging.INFO):
        persist_clauses(db_session, doc.id, result)
    db_session.commit()

    persisted_events = [r for r in caplog.records if r.getMessage() == "clauses_persisted"]
    assert len(persisted_events) == 1
    fields = persisted_events[0].fields
    assert set(fields.keys()) <= {"document_id", "stage", "count", "low_confidence_flag"}
    assert all(value != REDACTED_DISALLOWED for value in fields.values())
