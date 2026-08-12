"""Risk Engine pipeline orchestration — Phase 5 spec SS18-19.

Runs strictly after Phase 4 (Clause Understanding) has already persisted its
signals onto the pending `clause_analyses` row for a clause
(`clause_understanding_service.get_or_create_pending_analysis`):
`matched_patterns`, `financial_entities` (+ their unverified `evidence_spans`),
and `trigger`/`condition`/`consequence`/`affected_party` directly on the row.
This module never re-runs retrieval/entity/condition extraction — it reads
exactly what Phase 4 already collected (`ProcessingStage.UNDERSTANDING ->
SCORING`, API_and_Data_Models.md SS1) and updates that same row in place, per
the Phase 4 "pending row" design (docs/PROVISIONAL_DECISIONS.md "Phase 4:
pending clause_analyses row").

Never calls an LLM (Phase 5 spec header — no import of the generation
service exists here or anywhere it's reachable from).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.logging import get_logger, log_event
from app.models import db_models
from app.models.enums import DocumentType
from app.services.evidence_engine import persist_evidence
from app.services.risk_engine import (
    DEFAULT_RISK_ENGINE_CONFIG,
    EntitySignal,
    PatternSignal,
    RiskEngineConfig,
    score_clause,
)

logger = get_logger(__name__)


def _build_entity_signals(analysis: db_models.ClauseAnalysisORM) -> list[EntitySignal]:
    # Entities whose evidence span was, for some reason, never created
    # (should not happen via `entity_extraction_service.persist_entities`,
    # which always creates one) are skipped rather than scored with a
    # fabricated offset.
    return [
        EntitySignal(
            entity_type=entity.entity_type,
            value=entity.value,
            raw_text=entity.raw_text,
            start_char=entity.evidence_span.start_char,
            end_char=entity.evidence_span.end_char,
        )
        for entity in analysis.financial_entities
        if entity.evidence_span is not None
    ]


def _build_pattern_signals(analysis: db_models.ClauseAnalysisORM) -> list[PatternSignal]:
    return [
        PatternSignal(
            similarity_score=matched.similarity_score,
            lexical_score=matched.lexical_score,
            risk_category=matched.corpus_pattern.risk_category,
            risk_subcategory=matched.corpus_pattern.risk_subcategory,
            is_negative_example=matched.corpus_pattern.is_negative_example,
            taxonomy_version=matched.corpus_pattern.taxonomy_version,
            corpus_version=matched.corpus_pattern.corpus_version,
        )
        for matched in analysis.matched_patterns
    ]


def score_pending_analysis(
    db: Session,
    clause: db_models.Clause,
    analysis: db_models.ClauseAnalysisORM,
    *,
    document_type: DocumentType,
    config: RiskEngineConfig = DEFAULT_RISK_ENGINE_CONFIG,
) -> db_models.ClauseAnalysisORM:
    """Scores one clause's pending analysis and updates it in place. Raises
    on an internal engine failure (e.g. mixed corpus/taxonomy versions) —
    callers (`score_document`) are responsible for per-clause isolation."""
    entities = _build_entity_signals(analysis)
    patterns = _build_pattern_signals(analysis)

    result = score_clause(
        clause.raw_text,
        matched_patterns=patterns,
        entities=entities,
        trigger=analysis.trigger,
        condition_text=analysis.condition,
        consequence=analysis.consequence,
        document_type=document_type,
        clause_low_confidence_flag=clause.low_confidence_flag,
        page_number=clause.page_number,
        config=config,
    )

    persist_evidence(db, analysis, result.evidence)

    analysis.risk_category = result.risk_category
    analysis.risk_subcategory = result.risk_subcategory
    analysis.risk_level = result.risk_level
    analysis.risk_score = result.risk_score
    analysis.confidence_level = result.confidence_level
    analysis.confidence_score = result.confidence_score
    analysis.abstained = result.abstained
    analysis.abstain_reason = result.abstain_reason
    analysis.engine_version = result.engine_version

    db.flush()

    log_event(
        logger,
        "clause_risk_scored",
        clause_analysis_id=str(analysis.id),
        clause_id=str(clause.id),
        stage="scoring",
        risk_level=analysis.risk_level.value,
        risk_score=analysis.risk_score,
        confidence_level=analysis.confidence_level.value,
        confidence_score=analysis.confidence_score,
        abstained=analysis.abstained,
        engine_version=analysis.engine_version,
    )

    return analysis


@dataclass(frozen=True, slots=True)
class DocumentScoringSummary:
    total_clauses: int
    scored: int
    failed: int
    skipped_unanalyzed: int


def score_document(
    db: Session,
    document_id: uuid.UUID,
    *,
    document_type: DocumentType,
    config: RiskEngineConfig = DEFAULT_RISK_ENGINE_CONFIG,
) -> DocumentScoringSummary:
    """Scores every clause of a document that already has a pending
    `clause_analyses` row from Phase 4. Each clause is scored inside its own
    SAVEPOINT (`Session.begin_nested`) so a single clause's engine failure
    (e.g. a version-mismatch `ValueError`) rolls back only that clause's
    partial writes and never corrupts sibling clauses or leaves misleading
    partial data (Phase 5 spec SS19)."""
    clauses = db.scalars(select(db_models.Clause).where(db_models.Clause.document_id == document_id)).all()

    scored = 0
    failed = 0
    skipped = 0

    for clause in clauses:
        analysis = db.scalars(
            select(db_models.ClauseAnalysisORM).where(db_models.ClauseAnalysisORM.clause_id == clause.id)
        ).first()
        if analysis is None:
            skipped += 1
            continue

        try:
            with db.begin_nested():
                score_pending_analysis(db, clause, analysis, document_type=document_type, config=config)
            scored += 1
        except Exception:
            failed += 1
            log_event(
                logger,
                "clause_risk_scoring_failed",
                clause_id=str(clause.id),
                clause_analysis_id=str(analysis.id),
                stage="scoring",
                error_category="risk_engine_failure",
            )

    db.flush()
    return DocumentScoringSummary(
        total_clauses=len(clauses), scored=scored, failed=failed, skipped_unanalyzed=skipped
    )
