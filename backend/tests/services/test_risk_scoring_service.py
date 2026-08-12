"""Risk Engine pipeline orchestration tests — Phase 5 spec SS18-19.

Exercises `score_pending_analysis`/`score_document` against the real
`clause_analyses`/`financial_entities`/`evidence_spans`/`matched_patterns`
schema, continuing Phase 4's persistence pattern (see
tests/services/test_clause_understanding_service.py).
"""

from __future__ import annotations

import uuid

from sqlalchemy import select

from app.models import db_models
from app.models.enums import DocumentType, RiskLevel
from app.services.clause_understanding_service import run_clause_understanding
from app.services.risk_scoring_service import score_document, score_pending_analysis
from tests.conftest import make_clause, make_document

TAXONOMY_V1 = "taxonomy_v1"
CORPUS_V1 = "corpus_v1"


def _understood_clause(db_session, embedding_service, vector_store, raw_text: str, *, document=None):
    document = document or make_document()
    db_session.add(document)
    db_session.flush()
    clause = make_clause(document_id=document.id, raw_text=raw_text)
    db_session.add(clause)
    db_session.flush()

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
    return document, clause


class TestScorePendingAnalysis:
    def test_scores_a_clear_high_risk_clause_and_updates_row_in_place(
        self, db_session, embedding_service, vector_store
    ):
        document, clause = _understood_clause(
            db_session,
            embedding_service,
            vector_store,
            "Borrower shall pay a prepayment penalty equal to 5% of the outstanding "
            "principal if the loan is repaid in full within 24 months of disbursement.",
        )
        analysis = db_session.scalars(
            select(db_models.ClauseAnalysisORM).where(db_models.ClauseAnalysisORM.clause_id == clause.id)
        ).one()
        assert analysis.risk_level == RiskLevel.UNKNOWN  # still the Phase 4 pending placeholder

        score_pending_analysis(db_session, clause, analysis, document_type=DocumentType.LOAN)
        db_session.commit()

        db_session.refresh(analysis)
        assert analysis.risk_level == RiskLevel.HIGH
        assert analysis.abstained is False
        assert analysis.engine_version == "risk_engine_v1"
        assert analysis.confidence_score > 0.0

        # Entity-linked evidence spans created by Phase 4 are now verified.
        spans = db_session.scalars(
            select(db_models.EvidenceSpan).where(db_models.EvidenceSpan.clause_analysis_id == analysis.id)
        ).all()
        assert any(span.verified for span in spans)

    def test_no_id_is_the_same_row_not_a_new_one(self, db_session, embedding_service, vector_store):
        document, clause = _understood_clause(
            db_session, embedding_service, vector_store, "Borrower may prepay at any time without penalty."
        )
        analysis = db_session.scalars(
            select(db_models.ClauseAnalysisORM).where(db_models.ClauseAnalysisORM.clause_id == clause.id)
        ).one()
        analysis_id = analysis.id

        score_pending_analysis(db_session, clause, analysis, document_type=DocumentType.LOAN)
        db_session.commit()

        rows = db_session.scalars(
            select(db_models.ClauseAnalysisORM).where(db_models.ClauseAnalysisORM.clause_id == clause.id)
        ).all()
        assert len(rows) == 1
        assert rows[0].id == analysis_id
        assert rows[0].risk_level == RiskLevel.LOW


class TestScoreDocument:
    def test_scores_every_clause_with_a_pending_analysis(self, db_session, embedding_service, vector_store):
        document = make_document()
        db_session.add(document)
        db_session.flush()

        clause_a = make_clause(
            document_id=document.id,
            clause_index=0,
            raw_text="Borrower may prepay at any time without penalty.",
        )
        clause_b = make_clause(
            document_id=document.id,
            clause_index=1,
            raw_text="Borrower shall pay a prepayment penalty equal to 5% if repaid within 24 months.",
        )
        db_session.add_all([clause_a, clause_b])
        db_session.flush()

        for clause in (clause_a, clause_b):
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

        summary = score_document(db_session, document.id, document_type=DocumentType.LOAN)
        db_session.commit()

        assert summary.total_clauses == 2
        assert summary.scored == 2
        assert summary.failed == 0

        analyses = db_session.scalars(
            select(db_models.ClauseAnalysisORM)
            .join(db_models.Clause)
            .where(db_models.Clause.document_id == document.id)
        ).all()
        levels = {a.risk_level for a in analyses}
        assert RiskLevel.HIGH in levels
        assert RiskLevel.LOW in levels

    def test_one_clause_failure_does_not_corrupt_sibling_clauses(
        self, db_session, embedding_service, vector_store
    ):
        document = make_document()
        db_session.add(document)
        db_session.flush()

        good_clause = make_clause(
            document_id=document.id,
            clause_index=0,
            raw_text="Borrower shall pay a prepayment penalty equal to 5% if repaid within 24 months.",
        )
        broken_clause = make_clause(
            document_id=document.id, clause_index=1, raw_text="This clause will be corrupted before scoring."
        )
        db_session.add_all([good_clause, broken_clause])
        db_session.flush()

        for clause in (good_clause, broken_clause):
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

        # Force an internal engine failure for the second clause only: give
        # it two matched_patterns with conflicting taxonomy versions, which
        # `risk_engine.score_clause` explicitly rejects.
        broken_analysis = db_session.scalars(
            select(db_models.ClauseAnalysisORM).where(
                db_models.ClauseAnalysisORM.clause_id == broken_clause.id
            )
        ).one()
        pattern_a = db_models.CorpusPattern(
            id=uuid.uuid4(), pattern_text="x", taxonomy_version="taxonomy_v1", corpus_version="corpus_v1"
        )
        pattern_b = db_models.CorpusPattern(
            id=uuid.uuid4(), pattern_text="y", taxonomy_version="taxonomy_v2", corpus_version="corpus_v1"
        )
        db_session.add_all([pattern_a, pattern_b])
        db_session.flush()
        db_session.add_all(
            [
                db_models.MatchedPattern(
                    id=uuid.uuid4(),
                    clause_analysis_id=broken_analysis.id,
                    corpus_pattern_id=pattern_a.id,
                    similarity_score=0.5,
                    lexical_score=0.1,
                ),
                db_models.MatchedPattern(
                    id=uuid.uuid4(),
                    clause_analysis_id=broken_analysis.id,
                    corpus_pattern_id=pattern_b.id,
                    similarity_score=0.5,
                    lexical_score=0.1,
                ),
            ]
        )
        db_session.commit()

        summary = score_document(db_session, document.id, document_type=DocumentType.LOAN)
        db_session.commit()

        assert summary.total_clauses == 2
        assert summary.scored == 1
        assert summary.failed == 1

        good_analysis = db_session.scalars(
            select(db_models.ClauseAnalysisORM).where(db_models.ClauseAnalysisORM.clause_id == good_clause.id)
        ).one()
        assert good_analysis.risk_level == RiskLevel.HIGH  # unaffected by the sibling failure

        db_session.refresh(broken_analysis)
        # The broken clause's row was never corrupted into a misleading
        # scored state — it remains the untouched Phase 4 pending placeholder.
        assert broken_analysis.risk_level == RiskLevel.UNKNOWN
        assert broken_analysis.engine_version == "unscored"
