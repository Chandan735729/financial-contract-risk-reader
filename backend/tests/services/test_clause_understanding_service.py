"""Clause Understanding orchestrator tests — Phase 4 spec (architecture:
retrieval + entities + conditions all feed one pending clause_analyses row;
none of them decide risk_level here).
"""

from __future__ import annotations

import uuid

from sqlalchemy import select

from app.models import db_models
from app.models.enums import ConfidenceLevel, DocumentType, RiskLevel
from app.services.clause_understanding_service import (
    get_or_create_pending_analysis,
    run_clause_understanding,
)
from app.services.retrieval_service import index_corpus_patterns
from tests.conftest import make_clause, make_document

TAXONOMY_V1 = "taxonomy_v1"
CORPUS_V1 = "corpus_v1"


def _make_clause(db_session, raw_text: str) -> db_models.Clause:
    doc = make_document()
    clause = make_clause(document_id=doc.id, raw_text=raw_text)
    db_session.add_all([doc, clause])
    db_session.flush()
    return clause


class TestPendingAnalysisCreation:
    def test_creates_unknown_abstained_placeholder(self, db_session):
        clause = _make_clause(db_session, "Some clause text.")
        analysis = get_or_create_pending_analysis(db_session, clause, taxonomy_version=TAXONOMY_V1)
        db_session.commit()

        assert analysis.risk_level == RiskLevel.UNKNOWN
        assert analysis.abstained is True
        assert analysis.abstain_reason
        assert analysis.confidence_level == ConfidenceLevel.LOW
        assert analysis.risk_category is None
        assert analysis.taxonomy_version == TAXONOMY_V1

    def test_is_idempotent_returns_same_row_on_second_call(self, db_session):
        clause = _make_clause(db_session, "Some clause text.")
        first = get_or_create_pending_analysis(db_session, clause, taxonomy_version=TAXONOMY_V1)
        db_session.commit()
        second = get_or_create_pending_analysis(db_session, clause, taxonomy_version=TAXONOMY_V1)
        db_session.commit()

        assert first.id == second.id
        count = db_session.scalar(
            select(db_models.ClauseAnalysisORM)
            .where(db_models.ClauseAnalysisORM.clause_id == clause.id)
            .limit(1)
        )
        assert count is not None
        all_rows = db_session.scalars(
            select(db_models.ClauseAnalysisORM).where(db_models.ClauseAnalysisORM.clause_id == clause.id)
        ).all()
        assert len(all_rows) == 1

    def test_pending_row_passes_existing_pydantic_unknown_abstained_invariant(self, db_session):
        # The placeholder state must satisfy the same binding rule Phase 0
        # already enforces on the public ClauseAnalysis schema: UNKNOWN
        # requires abstained=True and vice versa.
        clause = _make_clause(db_session, "Some clause text.")
        analysis = get_or_create_pending_analysis(db_session, clause, taxonomy_version=TAXONOMY_V1)
        db_session.commit()
        assert (analysis.risk_level == RiskLevel.UNKNOWN) == analysis.abstained


class TestFullPipeline:
    def test_run_clause_understanding_persists_all_three_signal_streams(
        self, db_session, embedding_service, vector_store
    ):
        pattern = db_models.CorpusPattern(
            id=uuid.uuid4(),
            pattern_text="Borrower shall pay a prepayment penalty equal to 2% if repaid within 12 months.",
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

        clause = _make_clause(
            db_session,
            "If the borrower repays early within 12 months, a 2% prepayment charge applies.",
        )

        result = run_clause_understanding(
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

        assert result.entity_count == 2  # "12 months" + "2%"
        assert result.condition_detected is True
        assert result.has_retrieval_signal is True
        assert result.matched_pattern_count >= 1

        analysis = db_session.get(db_models.ClauseAnalysisORM, result.clause_analysis_id)
        assert analysis is not None
        assert analysis.trigger is not None
        assert analysis.consequence is not None
        # Still not scored — Phase 4 never decides risk.
        assert analysis.risk_level == RiskLevel.UNKNOWN
        assert analysis.abstained is True

        entities = db_session.scalars(
            select(db_models.FinancialEntity).where(
                db_models.FinancialEntity.clause_analysis_id == analysis.id
            )
        ).all()
        assert len(entities) == 2

        matches = db_session.scalars(
            select(db_models.MatchedPattern).where(db_models.MatchedPattern.clause_analysis_id == analysis.id)
        ).all()
        assert len(matches) >= 1

    def test_run_clause_understanding_handles_empty_corpus_gracefully(
        self, db_session, embedding_service, vector_store
    ):
        clause = _make_clause(db_session, "If the borrower defaults, the lender may terminate.")
        result = run_clause_understanding(
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

        assert result.has_retrieval_signal is False
        assert result.matched_pattern_count == 0
        assert result.condition_detected is True  # condition extraction still works independent of retrieval

    def test_run_clause_understanding_never_sets_risk_category(
        self, db_session, embedding_service, vector_store
    ):
        clause = _make_clause(
            db_session, "Borrower shall pay a prepayment penalty equal to 2% within 12 months."
        )
        result = run_clause_understanding(
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
        analysis = db_session.get(db_models.ClauseAnalysisORM, result.clause_analysis_id)
        assert analysis is not None
        assert analysis.risk_category is None
