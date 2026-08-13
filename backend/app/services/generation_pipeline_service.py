"""Generation pipeline orchestration — wires `generation_service.py`'s
per-clause explain function into the persisted `clause_analyses` pipeline.
Plays the same role for this stage that `risk_scoring_service.py` plays for
Phase 5: this module owns DB reads/writes, cost control, and safe logging;
`generation_service.py` stays a pure function of its inputs, same
separation as `risk_engine.py` vs `risk_scoring_service.py`.

Runs strictly after `risk_scoring_service.score_document` has already
scored a clause (`clause_analyses.risk_level` is no longer the Phase 4
UNKNOWN/abstained-pending placeholder). Cost control
(Security_and_Privacy_v2.md SS8 "Per-document caps on LLM explanation
calls..."): only HIGH/MEDIUM clauses are eligible
(`generation_config.GENERATION_ELIGIBLE_RISK_LEVELS`), and a per-document
call cap (`Settings.generation_max_calls_per_document`) bounds total spend
regardless of how many HIGH/MEDIUM clauses a single adversarial document
contains.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.logging import get_logger, log_event
from app.core.metrics import (
    EXPLANATIONS_FALLBACK_USED,
    EXPLANATIONS_GENERATED,
    EXPLANATIONS_GENERATION_FAILED,
    metrics,
)
from app.models import db_models
from app.models.enums import DocumentType
from app.models.schemas import ClauseAnalysis
from app.models.schemas import EvidenceSpan as EvidenceSpanSchema
from app.models.schemas import FinancialEntity as FinancialEntitySchema
from app.services.generation_config import (
    GENERATION_ELIGIBLE_RISK_LEVELS,
    GENERATION_SKIPPED_MODEL_VERSION,
    MODEL_VERSION,
)
from app.services.generation_models import GenerationOutcome
from app.services.generation_service import generate_explanation
from app.services.llm_client import GenerationLLMClient, LLMGenerationError, build_llm_client

logger = get_logger(__name__)


def _to_clause_analysis(
    clause: db_models.Clause, analysis: db_models.ClauseAnalysisORM, document_type: DocumentType
) -> ClauseAnalysis:
    """Assembles the canonical Pydantic view Generation Service/Grounding
    Guard expect (Grounding_and_Evidence_Spec.md SS4's `ClauseAnalysis`
    parameter) from the ORM rows Phase 4/5 already persisted. `clause_id`/
    `document_id`/`clause_index`/`document_type`/`section_heading`/
    `raw_text` live on the parent `Clause`/`Document`, not on
    `ClauseAnalysisORM` itself (API_and_Data_Models.md SS2's table split) --
    this is the one place that reassembles the split back into the schema's
    flat shape. Built with explicit keyword construction rather than
    `model_validate(orm_row, from_attributes=True)`: `FinancialEntity`'s ORM
    column is `entity_type`, not the schema's `type`, so a blind
    attribute-reflection pass would silently produce the wrong field.
    `matched_patterns` is intentionally left empty -- Generation Service
    never reads corpus retrieval matches (Grounding_and_Evidence_Spec.md SS1:
    the LLM explains evidence/entities, not corpus similarity).
    """
    return ClauseAnalysis(
        clause_id=clause.id,
        document_id=clause.document_id,
        clause_index=clause.clause_index,
        document_type=document_type,
        section_heading=clause.section_heading,
        raw_text=clause.raw_text,
        risk_category=analysis.risk_category,
        risk_subcategory=analysis.risk_subcategory,
        taxonomy_version=analysis.taxonomy_version,
        trigger=analysis.trigger,
        condition=analysis.condition,
        consequence=analysis.consequence,
        affected_party=analysis.affected_party,
        financial_entities=[
            FinancialEntitySchema(
                type=entity.entity_type, value=entity.value, unit=entity.unit, raw_text=entity.raw_text
            )
            for entity in analysis.financial_entities
        ],
        evidence_spans=[
            EvidenceSpanSchema(
                text=span.text,
                start_char=span.start_char,
                end_char=span.end_char,
                page_number=span.page_number,
                verified=span.verified,
            )
            for span in analysis.evidence_spans
        ],
        matched_patterns=[],
        risk_level=analysis.risk_level,
        risk_score=analysis.risk_score,
        confidence_level=analysis.confidence_level,
        confidence_score=analysis.confidence_score,
        abstained=analysis.abstained,
        abstain_reason=analysis.abstain_reason,
        explanation=analysis.explanation,
        explanation_grounded=analysis.explanation_grounded,
        model_version=analysis.model_version,
        engine_version=analysis.engine_version,
        created_at=analysis.created_at,
    )


def _mark_skipped(analysis: db_models.ClauseAnalysisORM) -> None:
    """Generation was never attempted for this clause (ineligible risk level
    or the per-document cap was reached). Distinct from
    `clause_understanding_service.PENDING_MODEL_VERSION` ("unscored" --
    Risk Engine has not run yet): here the Risk Engine already decided this
    clause's level, and the Generation pipeline is the one deciding not to
    spend a call on it -- see `generation_config`'s module docstring for the
    full three-state model_version design.
    """
    analysis.explanation = None
    analysis.explanation_grounded = None
    analysis.model_version = GENERATION_SKIPPED_MODEL_VERSION


def _mark_attempted(analysis: db_models.ClauseAnalysisORM, outcome: GenerationOutcome) -> None:
    analysis.explanation = outcome.explanation
    analysis.explanation_grounded = outcome.explanation_grounded
    analysis.model_version = outcome.model_version


@dataclass(frozen=True, slots=True)
class DocumentGenerationSummary:
    total_clauses: int
    eligible: int
    grounded: int
    fallback: int
    skipped_ineligible_risk_level: int
    skipped_cost_cap: int
    failed: int
    skipped_unanalyzed: int


def generate_pending_explanations(
    db: Session,
    document_id: uuid.UUID,
    *,
    document_type: DocumentType,
    settings: Settings,
    client: GenerationLLMClient | None = None,
) -> DocumentGenerationSummary:
    """Generates explanations for every HIGH/MEDIUM, already-scored clause
    of a document, up to `settings.generation_max_calls_per_document`. Each
    clause is processed inside its own SAVEPOINT (`Session.begin_nested`),
    mirroring `risk_scoring_service.score_document`'s per-clause isolation,
    so one clause's generation failure never corrupts sibling clauses or
    leaves misleading partial data.

    `client` is injectable so callers (and every test) can supply a fake
    `GenerationLLMClient` instead of the real Anthropic-backed one -- the
    real client is built lazily, once, from `settings` only when needed and
    not already supplied.
    """
    clauses = db.scalars(select(db_models.Clause).where(db_models.Clause.document_id == document_id)).all()

    resolved_client = client
    client_error: LLMGenerationError | None = None
    client_resolved = client is not None

    eligible = 0
    grounded = 0
    fallback = 0
    skipped_ineligible = 0
    skipped_cost_cap = 0
    failed = 0
    skipped_unanalyzed = 0
    calls_made = 0

    for clause in clauses:
        analysis = db.scalars(
            select(db_models.ClauseAnalysisORM).where(db_models.ClauseAnalysisORM.clause_id == clause.id)
        ).first()
        if analysis is None:
            skipped_unanalyzed += 1
            continue

        if analysis.risk_level not in GENERATION_ELIGIBLE_RISK_LEVELS:
            skipped_ineligible += 1
            with db.begin_nested():
                _mark_skipped(analysis)
            continue

        eligible += 1

        if calls_made >= settings.generation_max_calls_per_document:
            skipped_cost_cap += 1
            with db.begin_nested():
                _mark_skipped(analysis)
            continue

        if not client_resolved:
            client_resolved = True
            try:
                resolved_client = build_llm_client(settings)
            except LLMGenerationError as exc:
                client_error = exc

        if resolved_client is None:
            failed += 1
            category = client_error.category if client_error is not None else "no_client"
            with db.begin_nested():
                analysis.explanation = None
                analysis.explanation_grounded = False
                # A real model_version is still recorded (not the "skipped"
                # placeholder) because this is an operational failure to
                # attempt, not a deliberate cost-control decision -- see
                # generation_config's module docstring.
                analysis.model_version = MODEL_VERSION
            log_event(
                logger,
                "clause_explanation_generation_failed",
                clause_id=str(clause.id),
                clause_analysis_id=str(analysis.id),
                stage="generating",
                error_category=f"generation_failed:{category}",
            )
            metrics.increment(EXPLANATIONS_GENERATION_FAILED)
            continue

        calls_made += 1
        try:
            with db.begin_nested():
                clause_analysis = _to_clause_analysis(clause, analysis, document_type)
                outcome = generate_explanation(
                    resolved_client,
                    clause_analysis,
                    max_retries=settings.generation_max_retries,
                    max_output_tokens=settings.generation_max_output_tokens,
                )
                _mark_attempted(analysis, outcome)
            if outcome.explanation_grounded:
                grounded += 1
            else:
                fallback += 1
                metrics.increment(EXPLANATIONS_FALLBACK_USED)
            metrics.increment(EXPLANATIONS_GENERATED)
            log_event(
                logger,
                "clause_explanation_generated",
                clause_analysis_id=str(analysis.id),
                clause_id=str(clause.id),
                stage="generating",
                risk_level=analysis.risk_level.value,
                model_version=analysis.model_version,
                error_category=outcome.failure_category,
            )
        except Exception:
            failed += 1
            log_event(
                logger,
                "clause_explanation_generation_failed",
                clause_id=str(clause.id),
                clause_analysis_id=str(analysis.id),
                stage="generating",
                error_category="generation_pipeline_failure",
            )
            metrics.increment(EXPLANATIONS_GENERATION_FAILED)

    db.flush()
    return DocumentGenerationSummary(
        total_clauses=len(clauses),
        eligible=eligible,
        grounded=grounded,
        fallback=fallback,
        skipped_ineligible_risk_level=skipped_ineligible,
        skipped_cost_cap=skipped_cost_cap,
        failed=failed,
        skipped_unanalyzed=skipped_unanalyzed,
    )
