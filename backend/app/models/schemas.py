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
