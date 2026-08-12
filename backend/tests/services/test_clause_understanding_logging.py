"""Logging-safety tests for the Clause Understanding pipeline — Phase 4
spec SS20/SS23.

Confirms none of retrieval, entity extraction, or condition extraction ever
logs raw clause content, entity raw_text, or corpus pattern text — only the
same safe metadata allowlist the rest of the backend uses
(Security_and_Privacy_v2.md SS6).
"""

from __future__ import annotations

import logging
import uuid

from app.core.logging import REDACTED_DISALLOWED
from app.models import db_models
from app.models.enums import DocumentType
from app.services.clause_understanding_service import run_clause_understanding
from app.services.retrieval_service import index_corpus_patterns
from tests.conftest import make_clause, make_document

TAXONOMY_V1 = "taxonomy_v1"
CORPUS_V1 = "corpus_v1"

_SENSITIVE_CLAUSE_TEXT = (
    "Borrower John Smith, account number 1234567890, shall pay a confidential "
    "2% prepayment penalty within 12 months of disbursement."
)
_SENSITIVE_PATTERN_TEXT = "Borrower shall pay a prepayment penalty equal to 2% if repaid within 12 months."


def test_run_clause_understanding_never_logs_clause_or_pattern_text(
    db_session, embedding_service, vector_store, caplog
):
    pattern = db_models.CorpusPattern(
        id=uuid.uuid4(),
        pattern_text=_SENSITIVE_PATTERN_TEXT,
        risk_category=db_models.RiskCategory.FINANCIAL_COST,
        risk_subcategory="prepayment_penalty",
        source="scraped_indian",
        taxonomy_version=TAXONOMY_V1,
        corpus_version=CORPUS_V1,
        is_negative_example=False,
    )
    db_session.add(pattern)
    db_session.commit()
    index_corpus_patterns(
        db_session,
        embedding_service=embedding_service,
        vector_store=vector_store,
        taxonomy_version=TAXONOMY_V1,
        corpus_version=CORPUS_V1,
    )

    doc = make_document()
    clause = make_clause(document_id=doc.id, raw_text=_SENSITIVE_CLAUSE_TEXT)
    db_session.add_all([doc, clause])
    db_session.flush()

    with caplog.at_level(logging.DEBUG):
        run_clause_understanding(
            db_session,
            clause,
            document_type=DocumentType.LOAN,
            taxonomy_version=TAXONOMY_V1,
            corpus_version=CORPUS_V1,
            embedding_service=embedding_service,
            vector_store=vector_store,
            top_k=5,
            min_similarity_floor=0.3,
            min_lexical_floor=0.1,
        )
    db_session.commit()

    log_text = "\n".join(record.getMessage() for record in caplog.records)
    log_text += "\n".join(str(getattr(record, "fields", "")) for record in caplog.records)

    assert _SENSITIVE_CLAUSE_TEXT not in log_text
    assert _SENSITIVE_PATTERN_TEXT not in log_text
    assert "John Smith" not in log_text
    assert "1234567890" not in log_text
    assert "prepayment penalty" not in log_text.lower()


def test_all_log_events_only_carry_allowlisted_fields(db_session, embedding_service, vector_store, caplog):
    doc = make_document()
    clause = make_clause(document_id=doc.id, raw_text=_SENSITIVE_CLAUSE_TEXT)
    db_session.add_all([doc, clause])
    db_session.flush()

    with caplog.at_level(logging.DEBUG):
        run_clause_understanding(
            db_session,
            clause,
            document_type=DocumentType.LOAN,
            taxonomy_version=TAXONOMY_V1,
            corpus_version=CORPUS_V1,
            embedding_service=embedding_service,
            vector_store=vector_store,
            top_k=5,
            min_similarity_floor=0.3,
            min_lexical_floor=0.1,
        )
    db_session.commit()

    understanding_events = [
        r
        for r in caplog.records
        if r.getMessage() in ("clause_understanding_completed", "retrieval_matches_persisted")
    ]
    assert understanding_events
    for record in understanding_events:
        fields = getattr(record, "fields", {})
        assert all(value != REDACTED_DISALLOWED for value in fields.values())
