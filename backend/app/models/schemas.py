"""Pydantic v2 schemas — canonical `ClauseAnalysis` contract.

Mirrors the JSON schema in Risk_Taxonomy_and_Labeling_Spec.md SS6 exactly.
This is the *internal* canonical representation (includes `matched_patterns`,
which the public `/report` API response intentionally omits — see
`frontend/src/types/clauseAnalysis.ts` for the public-shape rationale). A
slimmed public response serializer belongs with the actual `/report`
endpoint implementation in a later phase, not Phase 0.

Binding rules enforced here, not just documented (PRD_v2.md SS4):
  - `risk_level` and confidence are always separate fields — never merged.
  - `abstained` and `risk_level == UNKNOWN` are kept consistent with each
    other, since abstention is defined as the mechanism that produces
    UNKNOWN (AI_Risk_Engine_Design.md SS6).
  - A `HIGH`/`MEDIUM` clause must carry at least one verified evidence span
    (PRD_v2.md Product Principle 5) — enforced at the schema boundary so an
    unevidenced HIGH/MEDIUM can never even be constructed, let alone shown.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.enums import ConfidenceLevel, DocumentType, RiskCategory, RiskLevel

FinancialEntityType = Literal["percentage", "amount", "fee", "rate", "time_period"]


class FinancialEntity(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    type: FinancialEntityType
    value: str
    unit: str | None = None
    raw_text: str


class EvidenceSpan(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    text: str
    start_char: int = Field(ge=0)
    end_char: int = Field(ge=0)
    page_number: int | None = None
    verified: bool = False

    @model_validator(mode="after")
    def _check_span_order(self) -> EvidenceSpan:
        if self.end_char < self.start_char:
            raise ValueError("end_char must be >= start_char")
        return self


class MatchedPattern(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    pattern_id: uuid.UUID
    source: str | None = None
    similarity_score: float = Field(ge=0.0, le=1.0)
    lexical_score: float = Field(ge=0.0, le=1.0)


class ClauseAnalysis(BaseModel):
    """Canonical per-clause analysis record (Risk_Taxonomy_and_Labeling_Spec.md SS6)."""

    model_config = ConfigDict(from_attributes=True)

    clause_id: uuid.UUID
    document_id: uuid.UUID
    clause_index: int = Field(ge=0)
    document_type: DocumentType
    section_heading: str | None = None
    raw_text: str

    risk_category: RiskCategory | None = None
    risk_subcategory: str | None = None
    taxonomy_version: str

    trigger: str | None = None
    condition: str | None = None
    consequence: str | None = None
    affected_party: str | None = None

    financial_entities: list[FinancialEntity] = Field(default_factory=list)
    evidence_spans: list[EvidenceSpan] = Field(default_factory=list)
    matched_patterns: list[MatchedPattern] = Field(default_factory=list)

    risk_level: RiskLevel
    risk_score: float = Field(ge=0.0, le=1.0)
    confidence_level: ConfidenceLevel
    confidence_score: float = Field(ge=0.0, le=1.0)
    abstained: bool
    abstain_reason: str | None = None

    explanation: str | None = None
    explanation_grounded: bool | None = None

    model_version: str
    engine_version: str = Field(
        default=..., description="Risk Engine weights/threshold version (API_and_Data_Models.md SS2)."
    )
    created_at: datetime

    @model_validator(mode="after")
    def _abstention_matches_unknown(self) -> ClauseAnalysis:
        if self.abstained and self.risk_level != RiskLevel.UNKNOWN:
            raise ValueError("abstained=True requires risk_level == UNKNOWN (AI_Risk_Engine_Design.md SS6)")
        if self.risk_level == RiskLevel.UNKNOWN and not self.abstained:
            raise ValueError(
                "risk_level == UNKNOWN requires abstained=True (UNKNOWN is produced by abstention)"
            )
        if self.abstained and not self.abstain_reason:
            raise ValueError("abstained=True requires a non-empty abstain_reason")
        return self

    @model_validator(mode="after")
    def _high_medium_requires_verified_evidence(self) -> ClauseAnalysis:
        if self.risk_level in (RiskLevel.HIGH, RiskLevel.MEDIUM) and not any(
            span.verified for span in self.evidence_spans
        ):
            raise ValueError(
                "risk_level HIGH/MEDIUM requires at least one verified evidence span "
                "(PRD_v2.md Product Principle 5; Grounding_and_Evidence_Spec.md SS2)"
            )
        return self


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    environment: str


class DocumentUploadResponse(BaseModel):
    """`POST /documents` response (API_and_Data_Models.md SS3) — deliberately
    just these two fields. No filesystem path, storage key, or parsed
    content ever appears in an API response (Phase 2 spec SS1)."""

    document_id: uuid.UUID
    access_token: str


class ApiErrorDetail(BaseModel):
    """Mirrors `frontend/src/types/api.ts`'s `ApiErrorDetail` exactly — the
    same shape `core/errors.py` already uses for the top-level `{"error":
    {...}}` envelope, reused here as the `status`/`report` endpoints'
    embedded `error` field (API_and_Data_Models.md SS3)."""

    code: str
    user_message: str
    request_id: uuid.UUID


class DocumentStatusResponse(BaseModel):
    """`GET /documents/{id}/status` response (API_and_Data_Models.md SS3;
    `frontend/src/types/api.ts`'s `ProcessingStatus`). Stage/error only — no
    internal error category, exception type, or implementation detail ever
    appears here (Security_and_Privacy_v2.md SS6)."""

    document_id: uuid.UUID
    document_type: DocumentType
    document_type_confidence: float | None = None
    stage: Literal[
        "queued",
        "parsing",
        "segmenting",
        "understanding",
        "scoring",
        "generating",
        "verifying",
        "completed",
        "failed",
    ]
    error: ApiErrorDetail | None = None


class ReportClauseAnalysis(BaseModel):
    """The `analysis` object inside each `/report` clause
    (API_and_Data_Models.md SS3; `frontend/src/types/clauseAnalysis.ts`'s
    `ClauseAnalysis`). Intentionally omits `matched_patterns` — corpus
    retrieval internals are exposed only via the separate evidence-detail
    endpoint, never the main report (see that module's header comment)."""

    model_config = ConfigDict(from_attributes=True)

    risk_category: RiskCategory | None = None
    risk_subcategory: str | None = None
    taxonomy_version: str

    trigger: str | None = None
    condition: str | None = None
    consequence: str | None = None
    affected_party: str | None = None

    risk_level: RiskLevel
    risk_score: float
    confidence_level: ConfidenceLevel
    confidence_score: float
    abstained: bool
    abstain_reason: str | None = None

    financial_entities: list[FinancialEntity] = Field(default_factory=list)
    evidence_spans: list[EvidenceSpan] = Field(default_factory=list)

    explanation: str | None = None
    explanation_grounded: bool | None = None

    model_version: str
    engine_version: str


class ReportClause(BaseModel):
    """One clause in a `/report` response. `analysis` is `None` only for the
    rare partial-failure case where clause understanding never produced a
    `clause_analyses` row for this clause at all (Phase 8: clause-level
    failure isolation) — distinct from a normal `UNKNOWN`/abstained
    analysis, which always populates `analysis` with `abstain_reason` set."""

    model_config = ConfigDict(from_attributes=True)

    clause_id: uuid.UUID
    clause_index: int
    section_heading: str | None = None
    raw_text: str
    analysis: ReportClauseAnalysis | None = None


class RiskSummary(BaseModel):
    high: int = 0
    medium: int = 0
    low: int = 0
    unknown: int = 0


class DocumentReportResponse(BaseModel):
    """`GET /documents/{id}/report` response (API_and_Data_Models.md SS3;
    `frontend/src/types/api.ts`'s `DocumentReport`)."""

    document_id: uuid.UUID
    document_type: DocumentType
    summary: RiskSummary
    clauses: list[ReportClause]


class EvidenceMatchedPattern(BaseModel):
    """Mirrors `frontend/src/types/clauseAnalysis.ts`'s `MatchedPattern` —
    the evidence-detail endpoint's slimmer public shape (no `source`, unlike
    the internal `MatchedPattern` schema above)."""

    model_config = ConfigDict(from_attributes=True)

    corpus_pattern_id: uuid.UUID
    similarity_score: float = Field(ge=0.0, le=1.0)
    lexical_score: float = Field(ge=0.0, le=1.0)


class ClauseEvidenceDetailResponse(BaseModel):
    """`GET /documents/{id}/clauses/{clause_id}/evidence` response
    (API_and_Data_Models.md SS3; `frontend/src/types/clauseAnalysis.ts`'s
    `ClauseEvidenceDetail`) — the one place `matched_patterns` (with scores)
    is intentionally exposed."""

    clause_id: uuid.UUID
    evidence_spans: list[EvidenceSpan] = Field(default_factory=list)
    financial_entities: list[FinancialEntity] = Field(default_factory=list)
    matched_patterns: list[EvidenceMatchedPattern] = Field(default_factory=list)
