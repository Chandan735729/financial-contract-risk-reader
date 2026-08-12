"""Clause Understanding orchestrator — Technical_Architecture_v2.md SS2
("CLAUSE UNDERSTANDING (per clause, three parallel extractors)"), Phase 4
spec (architecture diagram: retrieval + entities + conditions all feed
Phase 5's Risk Engine; none of them decide risk here).

**Schema note (Phase 4 spec SS21, SS26):** `matched_patterns` and
`financial_entities` are children of `clause_analyses`, not `clauses`
directly — but `clause_analyses.risk_level`/`confidence_level` are NOT
NULL, and Phase 4 must not decide risk. `get_or_create_pending_analysis`
resolves this by creating (or reusing) a `clause_analyses` row in the
existing, already-validated "abstained pending" shape: `risk_level=UNKNOWN`,
`abstained=True`, `abstain_reason` explaining the row is unscored — exactly
the state Phase 0's `ClauseAnalysis` Pydantic model already requires
`UNKNOWN` + `abstained=True` to travel together. Phase 5 updates this same
row in place once it scores the clause; this is not a duplicate/parallel
representation (see docs/PROVISIONAL_DECISIONS.md "Phase 4: pending
clause_analyses row").
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.logging import get_logger, log_event
from app.models import db_models
from app.models.enums import ConfidenceLevel, DocumentType, RiskLevel
from app.services.condition_extraction_service import extract_condition
from app.services.embedding_service import EmbeddingService
from app.services.entity_extraction_service import extract_financial_entities, persist_entities
from app.services.retrieval.vector_store import ChromaVectorStore
from app.services.retrieval_service import persist_matches, retrieve_matches

logger = get_logger(__name__)

PENDING_MODEL_VERSION = "unscored"
PENDING_ENGINE_VERSION = "unscored"
PENDING_ABSTAIN_REASON = "Risk Engine has not yet scored this clause (Phase 4 signal collection only)."


@dataclass(frozen=True, slots=True)
class UnderstandingResult:
    clause_analysis_id: uuid.UUID
    entity_count: int
    matched_pattern_count: int
    has_retrieval_signal: bool
    condition_detected: bool


def get_or_create_pending_analysis(
    db: Session, clause: db_models.Clause, *, taxonomy_version: str
) -> db_models.ClauseAnalysisORM:
    existing = db.scalars(
        select(db_models.ClauseAnalysisORM).where(db_models.ClauseAnalysisORM.clause_id == clause.id)
    ).first()
    if existing is not None:
        return existing

    analysis = db_models.ClauseAnalysisORM(
        id=uuid.uuid4(),
        clause_id=clause.id,
        taxonomy_version=taxonomy_version,
        risk_level=RiskLevel.UNKNOWN,
        risk_score=0.0,
        confidence_level=ConfidenceLevel.LOW,
        confidence_score=0.0,
        abstained=True,
        abstain_reason=PENDING_ABSTAIN_REASON,
        model_version=PENDING_MODEL_VERSION,
        engine_version=PENDING_ENGINE_VERSION,
    )
    db.add(analysis)
    db.flush()
    return analysis


def run_clause_understanding(
    db: Session,
    clause: db_models.Clause,
    *,
    document_type: DocumentType,
    taxonomy_version: str,
    corpus_version: str,
    embedding_service: EmbeddingService,
    vector_store: ChromaVectorStore,
    top_k: int,
    min_similarity_floor: float,
    min_lexical_floor: float,
) -> UnderstandingResult:
    """Runs all three Phase 4 extractors for one clause and persists their
    output under a pending (unscored) `clause_analyses` row. Never sets
    `risk_category`/`risk_level` beyond the UNKNOWN/abstained placeholder —
    that remains exclusively the Risk Engine's decision (Phase 5).
    """
    analysis = get_or_create_pending_analysis(db, clause, taxonomy_version=taxonomy_version)

    entities = extract_financial_entities(clause.raw_text)
    persist_entities(db, analysis.id, entities)

    condition = extract_condition(clause.raw_text)
    analysis.trigger = condition.trigger
    analysis.condition = condition.condition
    analysis.consequence = condition.consequence
    analysis.affected_party = condition.affected_party

    retrieval_result = retrieve_matches(
        clause.raw_text,
        db=db,
        embedding_service=embedding_service,
        vector_store=vector_store,
        document_type=document_type,
        taxonomy_version=taxonomy_version,
        corpus_version=corpus_version,
        top_k=top_k,
        min_similarity_floor=min_similarity_floor,
        min_lexical_floor=min_lexical_floor,
    )
    persist_matches(db, analysis.id, retrieval_result)

    db.flush()

    log_event(
        logger,
        "clause_understanding_completed",
        clause_id=str(clause.id),
        clause_analysis_id=str(analysis.id),
        count=len(entities),
        stage="understanding",
    )

    return UnderstandingResult(
        clause_analysis_id=analysis.id,
        entity_count=len(entities),
        matched_pattern_count=len(retrieval_result.matches),
        has_retrieval_signal=retrieval_result.has_signal,
        condition_detected=condition.trigger is not None,
    )
