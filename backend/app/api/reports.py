"""`GET /documents/{id}/status`, `GET /documents/{id}/report`,
`GET /documents/{id}/clauses/{clause_id}/evidence` — API_and_Data_Models.md
SS3 (Phase 8).

Every route here depends on `require_document_access`, the single shared
access-token check (see `app/api/deps.py`) — there is no code path in this
module that reads clause/evidence/entity data without it. Responses are
built exclusively from the Pydantic schemas in `app/models/schemas.py`,
which — by construction — never include `matched_patterns` on the main
report (only the evidence-detail endpoint does), filesystem paths, access
tokens, prompts, or provider request/response data.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import require_document_access
from app.core.errors import ApiError, error_user_message
from app.db.session import get_db
from app.models import db_models
from app.models.enums import ErrorCode
from app.models.schemas import (
    ApiErrorDetail,
    ClauseEvidenceDetailResponse,
    DocumentReportResponse,
    DocumentStatusResponse,
    EvidenceMatchedPattern,
    FinancialEntity,
    ReportClause,
    ReportClauseAnalysis,
    RiskSummary,
)
from app.models.schemas import EvidenceSpan as EvidenceSpanSchema

router = APIRouter(prefix="/v1/documents", tags=["reports"])


@router.get("/{document_id}/status", response_model=DocumentStatusResponse)
def get_document_status(
    request: Request,
    document: db_models.Document = Depends(require_document_access),
    db: Session = Depends(get_db),
) -> DocumentStatusResponse:
    job = db.scalars(
        select(db_models.ProcessingJob).where(db_models.ProcessingJob.document_id == document.id)
    ).one_or_none()
    stage = job.stage.value if job is not None else "queued"

    error_detail: ApiErrorDetail | None = None
    if job is not None and job.error_code is not None:
        try:
            code = ErrorCode(job.error_code)
        except ValueError:
            code = ErrorCode.INTERNAL_ERROR
        request_id = getattr(request.state, "request_id", uuid.uuid4())
        error_detail = ApiErrorDetail(
            code=code.value, user_message=error_user_message(code), request_id=request_id
        )

    return DocumentStatusResponse(
        document_id=document.id,
        document_type=document.document_type,
        document_type_confidence=document.document_type_confidence,
        stage=stage,
        error=error_detail,
    )


def _to_report_clause(clause: db_models.Clause) -> ReportClause:
    analysis_row = clause.analyses[0] if clause.analyses else None
    analysis: ReportClauseAnalysis | None = None
    if analysis_row is not None:
        analysis = ReportClauseAnalysis(
            risk_category=analysis_row.risk_category,
            risk_subcategory=analysis_row.risk_subcategory,
            taxonomy_version=analysis_row.taxonomy_version,
            trigger=analysis_row.trigger,
            condition=analysis_row.condition,
            consequence=analysis_row.consequence,
            affected_party=analysis_row.affected_party,
            risk_level=analysis_row.risk_level,
            risk_score=analysis_row.risk_score,
            confidence_level=analysis_row.confidence_level,
            confidence_score=analysis_row.confidence_score,
            abstained=analysis_row.abstained,
            abstain_reason=analysis_row.abstain_reason,
            financial_entities=[
                FinancialEntity(type=e.entity_type, value=e.value, unit=e.unit, raw_text=e.raw_text)
                for e in analysis_row.financial_entities
            ],
            evidence_spans=[
                EvidenceSpanSchema(
                    text=s.text,
                    start_char=s.start_char,
                    end_char=s.end_char,
                    page_number=s.page_number,
                    verified=s.verified,
                )
                for s in analysis_row.evidence_spans
            ],
            explanation=analysis_row.explanation,
            explanation_grounded=analysis_row.explanation_grounded,
            model_version=analysis_row.model_version,
            engine_version=analysis_row.engine_version,
        )

    return ReportClause(
        clause_id=clause.id,
        clause_index=clause.clause_index,
        section_heading=clause.section_heading,
        raw_text=clause.raw_text,
        analysis=analysis,
    )


@router.get("/{document_id}/report", response_model=DocumentReportResponse)
def get_document_report(
    document: db_models.Document = Depends(require_document_access),
    db: Session = Depends(get_db),
) -> DocumentReportResponse:
    clauses = db.scalars(
        select(db_models.Clause)
        .where(db_models.Clause.document_id == document.id)
        .order_by(db_models.Clause.clause_index)
    ).all()

    report_clauses = [_to_report_clause(clause) for clause in clauses]

    summary = RiskSummary()
    for rc in report_clauses:
        if rc.analysis is None:
            continue
        level = rc.analysis.risk_level.value.lower()
        if level == "high":
            summary.high += 1
        elif level == "medium":
            summary.medium += 1
        elif level == "low":
            summary.low += 1
        else:
            summary.unknown += 1

    return DocumentReportResponse(
        document_id=document.id,
        document_type=document.document_type,
        summary=summary,
        clauses=report_clauses,
    )


@router.get("/{document_id}/clauses/{clause_id}/evidence", response_model=ClauseEvidenceDetailResponse)
def get_clause_evidence(
    clause_id: uuid.UUID,
    document: db_models.Document = Depends(require_document_access),
    db: Session = Depends(get_db),
) -> ClauseEvidenceDetailResponse:
    # `require_document_access` only proves the caller owns `document_id` —
    # the clause must additionally be scoped to *that* document, never
    # resolved by `clause_id` alone (Phase 8 spec: "never allow direct
    # clause/evidence access without parent-document authorization").
    clause = db.scalars(
        select(db_models.Clause).where(
            db_models.Clause.id == clause_id, db_models.Clause.document_id == document.id
        )
    ).one_or_none()
    if clause is None:
        raise ApiError(ErrorCode.ACCESS_DENIED, status.HTTP_404_NOT_FOUND)

    analysis_row = clause.analyses[0] if clause.analyses else None
    if analysis_row is None:
        return ClauseEvidenceDetailResponse(clause_id=clause.id)

    return ClauseEvidenceDetailResponse(
        clause_id=clause.id,
        evidence_spans=[
            EvidenceSpanSchema(
                text=s.text,
                start_char=s.start_char,
                end_char=s.end_char,
                page_number=s.page_number,
                verified=s.verified,
            )
            for s in analysis_row.evidence_spans
        ],
        financial_entities=[
            FinancialEntity(type=e.entity_type, value=e.value, unit=e.unit, raw_text=e.raw_text)
            for e in analysis_row.financial_entities
        ],
        matched_patterns=[
            EvidenceMatchedPattern(
                corpus_pattern_id=m.corpus_pattern_id,
                similarity_score=m.similarity_score,
                lexical_score=m.lexical_score,
            )
            for m in analysis_row.matched_patterns
        ],
    )
