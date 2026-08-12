"""ClauseAnalysis contract tests — Risk_Taxonomy_and_Labeling_Spec.md SS6.

All clause text below is synthetic, written for this test suite only.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.models.enums import ConfidenceLevel, DocumentType, RiskCategory, RiskLevel
from app.models.schemas import ClauseAnalysis, EvidenceSpan, FinancialEntity, MatchedPattern


def _base_kwargs(**overrides) -> dict:
    defaults = dict(
        clause_id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        clause_index=4,
        document_type=DocumentType.LOAN,
        section_heading="4. Prepayment",
        raw_text="Synthetic: Borrower shall pay a prepayment penalty equal to 2%.",
        risk_category=RiskCategory.FINANCIAL_COST,
        risk_subcategory="prepayment_penalty",
        taxonomy_version="taxonomy_v1",
        trigger="repayment within 24 months",
        condition="full repayment",
        consequence="2% penalty",
        affected_party="borrower",
        financial_entities=[FinancialEntity(type="percentage", value="2", unit="%", raw_text="2%")],
        evidence_spans=[EvidenceSpan(text="2%", start_char=10, end_char=12, page_number=3, verified=True)],
        matched_patterns=[
            MatchedPattern(pattern_id=uuid.uuid4(), source="cuad", similarity_score=0.8, lexical_score=0.6)
        ],
        risk_level=RiskLevel.HIGH,
        risk_score=0.81,
        confidence_level=ConfidenceLevel.HIGH,
        confidence_score=0.92,
        abstained=False,
        abstain_reason=None,
        explanation="This clause appears to impose a 2% prepayment penalty.",
        explanation_grounded=True,
        model_version="gen-v0",
        engine_version="engine-v0",
        created_at=datetime.now(UTC),
    )
    defaults.update(overrides)
    return defaults


def test_valid_high_risk_clause_constructs_successfully():
    analysis = ClauseAnalysis(**_base_kwargs())
    assert analysis.risk_level == RiskLevel.HIGH
    assert analysis.confidence_level == ConfidenceLevel.HIGH


def test_json_round_trip_preserves_all_fields():
    analysis = ClauseAnalysis(**_base_kwargs())
    dumped = analysis.model_dump_json()
    restored = ClauseAnalysis.model_validate_json(dumped)
    assert restored == analysis


def test_risk_level_and_confidence_are_independent_fields():
    # HIGH risk with LOW confidence is a valid, important combination
    # (PRD_v2.md Product Principle 9) — the schema must not collapse them.
    analysis = ClauseAnalysis(
        **_base_kwargs(
            risk_level=RiskLevel.HIGH,
            confidence_level=ConfidenceLevel.LOW,
            confidence_score=0.35,
        )
    )
    assert analysis.risk_level == RiskLevel.HIGH
    assert analysis.confidence_level == ConfidenceLevel.LOW
    assert analysis.confidence_score == 0.35


def test_unknown_risk_level_requires_abstained_true():
    with pytest.raises(ValidationError, match="abstained"):
        ClauseAnalysis(
            **_base_kwargs(
                risk_level=RiskLevel.UNKNOWN,
                abstained=False,
                risk_category=None,
                risk_subcategory=None,
                evidence_spans=[],
                financial_entities=[],
                matched_patterns=[],
            )
        )


def test_abstained_true_requires_unknown_risk_level():
    with pytest.raises(ValidationError, match="UNKNOWN"):
        ClauseAnalysis(**_base_kwargs(abstained=True, abstain_reason="No evidence found."))


def test_abstained_requires_reason():
    with pytest.raises(ValidationError, match="abstain_reason"):
        ClauseAnalysis(
            **_base_kwargs(
                risk_level=RiskLevel.UNKNOWN,
                abstained=True,
                abstain_reason=None,
                risk_category=None,
                evidence_spans=[],
                financial_entities=[],
                matched_patterns=[],
            )
        )


def test_valid_unknown_abstention_case():
    analysis = ClauseAnalysis(
        **_base_kwargs(
            risk_level=RiskLevel.UNKNOWN,
            risk_score=0.3,
            abstained=True,
            abstain_reason="No retrieval match, rule hit, or extractable entity found for a substantive clause.",
            risk_category=None,
            risk_subcategory=None,
            confidence_level=ConfidenceLevel.LOW,
            confidence_score=0.2,
            evidence_spans=[],
            financial_entities=[],
            matched_patterns=[],
            explanation=None,
            explanation_grounded=None,
        )
    )
    assert analysis.risk_level == RiskLevel.UNKNOWN
    assert analysis.abstained is True


def test_high_risk_without_verified_evidence_span_rejected():
    with pytest.raises(ValidationError, match="verified evidence span"):
        ClauseAnalysis(
            **_base_kwargs(
                risk_level=RiskLevel.HIGH,
                evidence_spans=[EvidenceSpan(text="2%", start_char=10, end_char=12, verified=False)],
            )
        )


def test_medium_risk_without_any_evidence_span_rejected():
    with pytest.raises(ValidationError, match="verified evidence span"):
        ClauseAnalysis(**_base_kwargs(risk_level=RiskLevel.MEDIUM, evidence_spans=[]))


def test_low_risk_does_not_require_evidence_span():
    analysis = ClauseAnalysis(
        **_base_kwargs(
            risk_level=RiskLevel.LOW,
            risk_score=0.05,
            confidence_level=ConfidenceLevel.MEDIUM,
            confidence_score=0.6,
            evidence_spans=[],
            financial_entities=[],
            matched_patterns=[],
        )
    )
    assert analysis.risk_level == RiskLevel.LOW


def test_evidence_span_end_before_start_rejected():
    with pytest.raises(ValidationError):
        EvidenceSpan(text="x", start_char=10, end_char=5)


def test_financial_entity_rejects_unknown_type():
    with pytest.raises(ValidationError):
        FinancialEntity(type="not_a_real_type", value="5", raw_text="5%")


def test_risk_score_bounds_enforced():
    with pytest.raises(ValidationError):
        ClauseAnalysis(**_base_kwargs(risk_score=1.5))
    with pytest.raises(ValidationError):
        ClauseAnalysis(**_base_kwargs(confidence_score=-0.1))
