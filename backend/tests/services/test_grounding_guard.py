"""Grounding Guard tests — Grounding_and_Evidence_Spec.md SS7's five-case
minimum regression suite plus additional coverage. The most important
negative tests in this file: a fabricated fee, a fabricated legal
conclusion, and a risk-minimizing injection attempt must NEVER pass.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from app.models.enums import ConfidenceLevel, DocumentType, RiskLevel
from app.models.schemas import ClauseAnalysis, EvidenceSpan, FinancialEntity
from app.services.generation_models import GeneratedClaim, GeneratedExplanation
from app.services.grounding_guard import extract_claims, grounding_guard, supported_by_evidence

_RAW_TEXT = (
    "The Borrower shall pay a prepayment penalty of 2% of the outstanding "
    "principal if the loan is repaid in full within 24 months of the "
    "disbursement date."
)

_VERIFIED_SPAN = EvidenceSpan(
    text="prepayment penalty of 2%",
    start_char=_RAW_TEXT.index("prepayment penalty of 2%"),
    end_char=_RAW_TEXT.index("prepayment penalty of 2%") + len("prepayment penalty of 2%"),
    page_number=1,
    verified=True,
)
_UNVERIFIED_SPAN = EvidenceSpan(
    text="a completely different unverified phrase",
    start_char=0,
    end_char=10,
    page_number=1,
    verified=False,
)
_ENTITY = FinancialEntity(type="percentage", value="2", unit="%", raw_text="2%")


def _claim(text: str, claim_type: str = "risk_summary") -> GeneratedClaim:
    return GeneratedClaim(text=text, claim_type=claim_type)


class TestSupportedByEvidenceRequiredCases:
    """Grounding_and_Evidence_Spec.md SS7's five minimum required cases."""

    def test_positive_control_clean_explanation_is_supported(self):
        claim = _claim("The borrower must pay a prepayment penalty of 2% of the outstanding principal")
        assert supported_by_evidence(claim, [_VERIFIED_SPAN], [_ENTITY], _RAW_TEXT, RiskLevel.HIGH) is True

    def test_fabricated_fee_is_not_supported(self):
        claim = _claim("The borrower must pay a prepayment penalty of 5%")
        assert supported_by_evidence(claim, [_VERIFIED_SPAN], [_ENTITY], _RAW_TEXT, RiskLevel.HIGH) is False

    def test_fabricated_legal_conclusion_is_not_supported(self):
        claim = _claim("This clause is unenforceable")
        assert supported_by_evidence(claim, [_VERIFIED_SPAN], [_ENTITY], _RAW_TEXT, RiskLevel.HIGH) is False

    def test_fabricated_legal_conclusion_fails_even_when_otherwise_grounded(self):
        # The 2% figure is real and grounded, but the "illegal" assertion
        # must still fail the claim -- Security_and_Privacy_v2.md SS7:
        # "a technically 'grounded' claim that nonetheless asserts
        # illegality ... still fails the guard."
        claim = _claim("The 2% prepayment penalty in this clause is illegal")
        assert supported_by_evidence(claim, [_VERIFIED_SPAN], [_ENTITY], _RAW_TEXT, RiskLevel.HIGH) is False

    def test_near_verbatim_paraphrase_is_supported(self):
        claim = _claim("The lender charges a 2% prepayment penalty if you pay off the loan within 24 months")
        assert supported_by_evidence(claim, [_VERIFIED_SPAN], [_ENTITY], _RAW_TEXT, RiskLevel.HIGH) is True

    def test_partial_support_one_invented_detail_fails_whole_explanation(self):
        clean_claim = _claim("The borrower must pay a prepayment penalty of 2%")
        fabricated_claim = _claim("Late payments also incur a $500 fine")
        generated = GeneratedExplanation(
            text="explanation text",
            claims=(clean_claim, fabricated_claim),
        )
        clause = _clause_analysis(
            risk_level=RiskLevel.HIGH, evidence_spans=(_VERIFIED_SPAN,), entities=(_ENTITY,)
        )
        result = grounding_guard(clause, generated)
        assert result.passed is False
        assert fabricated_claim in result.unsupported_claims


class TestSupportedByEvidenceAdditionalCases:
    def test_fabricated_date_is_not_supported(self):
        claim = _claim("This penalty applies until March 15, 2026")
        assert supported_by_evidence(claim, [_VERIFIED_SPAN], [_ENTITY], _RAW_TEXT, RiskLevel.HIGH) is False

    def test_wholly_unrelated_fabricated_consequence_is_not_supported(self):
        claim = _claim("Your car will be repossessed if you miss a single payment")
        assert supported_by_evidence(claim, [_VERIFIED_SPAN], [_ENTITY], _RAW_TEXT, RiskLevel.HIGH) is False

    def test_risk_minimizing_claim_fails_for_high_risk_clause(self):
        claim = _claim("This clause is completely safe and poses no risk to you")
        assert supported_by_evidence(claim, [_VERIFIED_SPAN], [_ENTITY], _RAW_TEXT, RiskLevel.HIGH) is False

    def test_risk_minimizing_claim_fails_for_medium_risk_clause(self):
        claim = _claim("There is nothing to worry about here")
        assert supported_by_evidence(claim, [_VERIFIED_SPAN], [_ENTITY], _RAW_TEXT, RiskLevel.MEDIUM) is False

    def test_risk_minimizing_phrase_check_does_not_apply_below_medium(self):
        # The phrase itself is not language-policy-forbidden; below
        # MEDIUM the risk-minimization check (check #3) does not apply, so
        # this claim is judged purely on grounding (check #4), and a
        # genuinely grounded LOW-risk description passes.
        claim = _claim("This is a prepayment penalty of 2% and appears standard")
        assert supported_by_evidence(claim, [_VERIFIED_SPAN], [_ENTITY], _RAW_TEXT, RiskLevel.LOW) is True

    def test_unverified_evidence_span_does_not_ground_a_claim(self):
        claim = _claim("a completely different unverified phrase")
        assert (
            supported_by_evidence(
                claim, [_UNVERIFIED_SPAN], [], "unrelated raw text entirely", RiskLevel.HIGH
            )
            is False
        )

    def test_hallucinated_supporting_evidence_id_does_not_grant_a_pass(self):
        # The claim cites E99, which doesn't exist -- the guard must verify
        # the claim's *text* against the clause's real evidence, never trust
        # a self-reported ID.
        claim = GeneratedClaim(
            text="The borrower must pay a $10,000 penalty",
            claim_type="risk_summary",
            supporting_evidence_ids=("E99",),
        )
        assert supported_by_evidence(claim, [_VERIFIED_SPAN], [_ENTITY], _RAW_TEXT, RiskLevel.HIGH) is False

    def test_claim_grounded_via_raw_text_alone_without_a_matching_evidence_span(self):
        # Grounding_and_Evidence_Spec.md SS3 point 2(c): a claim may also be
        # supported by "a direct near-verbatim match elsewhere in raw_text",
        # not only by a promoted EvidenceSpan.
        claim = _claim("The loan was disbursed and the penalty period runs 24 months from that date")
        assert supported_by_evidence(claim, [], [], _RAW_TEXT, RiskLevel.HIGH) is True

    def test_financial_entity_value_grounds_a_normalized_claim(self):
        claim = _claim("The prepayment penalty is 2 percent")
        # entity.value == "2" grounds the digit even though the claim spells
        # "percent" rather than using the "%" symbol from raw_text -- the
        # surrounding descriptive words ("prepayment", "penalty") still need
        # to clear the lexical-overlap check independently (#4); the numeric
        # check (#1) and the descriptive check are not substitutes for one
        # another.
        assert supported_by_evidence(claim, [], [_ENTITY], _RAW_TEXT, RiskLevel.HIGH) is True

    def test_empty_claim_text_is_not_supported(self):
        claim = _claim("   ")
        assert supported_by_evidence(claim, [_VERIFIED_SPAN], [_ENTITY], _RAW_TEXT, RiskLevel.HIGH) is False


class TestExtractClaims:
    def test_extract_claims_returns_the_llm_self_reported_claims(self):
        claims = (_claim("a"), _claim("b"))
        generated = GeneratedExplanation(text="a. b.", claims=claims)
        assert extract_claims(generated) == claims


class TestGroundingGuard:
    def test_empty_claims_list_fails_closed(self):
        generated = GeneratedExplanation(text="Some explanation with no claims listed.", claims=())
        clause = _clause_analysis(
            risk_level=RiskLevel.HIGH, evidence_spans=(_VERIFIED_SPAN,), entities=(_ENTITY,)
        )
        result = grounding_guard(clause, generated)
        assert result.passed is False
        assert result.unsupported_claims == ()

    def test_all_claims_grounded_passes(self):
        claims = (
            _claim("The borrower must pay a prepayment penalty of 2%"),
            _claim("The penalty applies if the loan is repaid within 24 months"),
        )
        generated = GeneratedExplanation(text="explanation", claims=claims)
        clause = _clause_analysis(
            risk_level=RiskLevel.HIGH, evidence_spans=(_VERIFIED_SPAN,), entities=(_ENTITY,)
        )
        result = grounding_guard(clause, generated)
        assert result.passed is True
        assert result.unsupported_claims == ()


def _clause_analysis(*, risk_level: RiskLevel, evidence_spans, entities):
    """Minimal `ClauseAnalysis` builder local to this test module -- lighter
    than the full pipeline fixtures in test_generation_pipeline_service.py
    since these tests only exercise `grounding_guard`, which reads
    `raw_text`/`risk_level`/`evidence_spans`/`financial_entities` only.
    """
    return ClauseAnalysis(
        clause_id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        clause_index=0,
        document_type=DocumentType.LOAN,
        section_heading=None,
        raw_text=_RAW_TEXT,
        risk_category=None,
        risk_subcategory=None,
        taxonomy_version="taxonomy_v1",
        trigger=None,
        condition=None,
        consequence=None,
        affected_party=None,
        financial_entities=list(entities),
        evidence_spans=list(evidence_spans),
        matched_patterns=[],
        risk_level=risk_level,
        risk_score=0.81 if risk_level == RiskLevel.HIGH else 0.5,
        confidence_level=ConfidenceLevel.HIGH,
        confidence_score=0.9,
        abstained=False,
        abstain_reason=None,
        explanation=None,
        explanation_grounded=None,
        model_version="unscored",
        engine_version="risk_engine_v1",
        created_at=datetime.now(UTC),
    )
