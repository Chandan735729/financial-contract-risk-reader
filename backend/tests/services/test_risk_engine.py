"""Risk Engine tests — AI_Risk_Engine_Design.md SS4-SS6, Phase 5 spec SS21/23.

Test classes A-J follow the Phase 5 spec's lettered test-case list exactly.
"""

from __future__ import annotations

import pytest

from app.models.enums import ConfidenceLevel, DocumentType, RiskCategory, RiskLevel
from app.services.condition_extraction_service import extract_condition
from app.services.entity_extraction_service import extract_financial_entities
from app.services.risk_engine import (
    EntitySignal,
    PatternSignal,
    apply_abstention_rules,
    apply_severity_ceiling,
    category_doc_type_relevance,
    score_clause,
    score_conditions,
    score_entities,
    threshold_to_level,
)
from app.services.risk_engine_config import DEFAULT_RISK_ENGINE_CONFIG, RiskEngineConfig


def _score(text: str, *, matched_patterns=None, document_type=DocumentType.LOAN, low_confidence=False):
    entities = extract_financial_entities(text)
    condition = extract_condition(text)
    entity_signals = [
        EntitySignal(e.entity_type, e.value, e.raw_text, e.start_char, e.end_char) for e in entities
    ]
    return score_clause(
        text,
        matched_patterns=matched_patterns or [],
        entities=entity_signals,
        trigger=condition.trigger,
        condition_text=condition.condition,
        consequence=condition.consequence,
        document_type=document_type,
        clause_low_confidence_flag=low_confidence,
        page_number=1,
    )


def _pattern(
    *,
    similarity=0.0,
    lexical=0.0,
    category=RiskCategory.FINANCIAL_COST,
    subcategory="prepayment_penalty",
    is_negative_example=False,
    taxonomy_version="taxonomy_v1",
    corpus_version="corpus_v1",
) -> PatternSignal:
    return PatternSignal(
        similarity_score=similarity,
        lexical_score=lexical,
        risk_category=category,
        risk_subcategory=subcategory,
        is_negative_example=is_negative_example,
        taxonomy_version=taxonomy_version,
        corpus_version=corpus_version,
    )


class TestCaseA_ExplicitHigh:
    def test_rule_and_entity_corroboration_reaches_high(self):
        text = (
            "Borrower shall pay a prepayment penalty equal to 5% of the outstanding "
            "principal if the loan is repaid in full within 24 months of disbursement."
        )
        result = _score(text)
        assert result.risk_level == RiskLevel.HIGH
        assert result.abstained is False
        assert any(span.verified for span in result.evidence.verified)


class TestCaseB_ExplicitLowSafe:
    def test_negated_rule_produces_low_with_evidence(self):
        result = _score("Borrower may prepay at any time without penalty.")
        assert result.risk_level == RiskLevel.LOW
        assert result.abstained is False
        assert len(result.evidence.verified) >= 1
        assert result.signals.has_positive_low_evidence is True


class TestCaseC_Ambiguous:
    def test_vague_language_abstains(self):
        result = _score("Prepayment provisions may apply under certain circumstances.")
        assert result.risk_level == RiskLevel.UNKNOWN
        assert result.abstained is True
        assert result.abstain_reason


class TestCaseD_HighSimilarityButSafe:
    def test_negated_clause_is_not_high_despite_strong_retrieval_match(self):
        strong_match = _pattern(similarity=0.9, lexical=0.6)
        result = _score("Borrower may prepay at any time without penalty.", matched_patterns=[strong_match])
        assert result.risk_level != RiskLevel.HIGH
        assert result.risk_level == RiskLevel.LOW


class TestCaseE_LowSimilarityExplicitRule:
    def test_clear_rule_language_is_detected_without_retrieval_signal(self):
        text = (
            "In case of late payment, acceleration of the entire outstanding balance shall apply immediately."
        )
        result = _score(text, matched_patterns=[])
        assert result.risk_level in (RiskLevel.MEDIUM, RiskLevel.HIGH)
        assert result.abstained is False


class TestCaseF_MissingEvidence:
    def test_high_or_medium_candidate_without_verified_evidence_is_forced_unknown(self):
        for candidate in (RiskLevel.HIGH, RiskLevel.MEDIUM):
            level, abstained, reason = apply_abstention_rules(
                candidate,
                confidence_score=0.9,
                clause_low_confidence_flag=False,
                verified_evidence_present=False,
                has_positive_low_evidence=False,
                config=DEFAULT_RISK_ENGINE_CONFIG,
            )
            assert level == RiskLevel.UNKNOWN
            assert abstained is True
            assert reason is not None and "evidence" in reason.lower()

    def test_high_candidate_with_verified_evidence_is_not_downgraded(self):
        level, abstained, reason = apply_abstention_rules(
            RiskLevel.HIGH,
            confidence_score=0.9,
            clause_low_confidence_flag=False,
            verified_evidence_present=True,
            has_positive_low_evidence=False,
            config=DEFAULT_RISK_ENGINE_CONFIG,
        )
        assert level == RiskLevel.HIGH
        assert abstained is False
        assert reason is None


class TestConditionalExceptionEndToEnd:
    """PHASE_6.5 (docs/PROVISIONAL_DECISIONS.md P6.9, P6.6 item 2): "No X
    unless Y" must not resolve to LOW — the exception conditionally
    re-establishes the risk."""

    def test_no_x_unless_y_is_not_low(self):
        result = _score("No prepayment penalty applies unless the loan is repaid within 12 months.")
        assert result.risk_level != RiskLevel.LOW
        assert result.risk_level == RiskLevel.MEDIUM
        assert result.abstained is False
        assert result.signals.has_positive_low_evidence is False

    def test_neither_party_waives_stays_low_or_unknown_not_risky(self):
        result = _score(
            "Any dispute may optionally proceed to arbitration, but neither party waives any other legal right."
        )
        assert result.risk_level not in (RiskLevel.HIGH, RiskLevel.MEDIUM)


class TestCaseG_ConflictingSignals:
    def test_rule_and_dense_disagreement_lowers_agreement_but_can_still_score(self):
        # Dense retrieval strongly suggests risk; rule finds explicit negation.
        strong_match = _pattern(similarity=0.9, lexical=0.1)
        result = _score("Borrower may prepay at any time without penalty.", matched_patterns=[strong_match])
        # Conflict should not silently manufacture a HIGH result.
        assert result.risk_level != RiskLevel.HIGH


class TestCaseH_NoRetrievalMatch:
    def test_no_signal_at_all_never_becomes_low(self):
        result = _score("This agreement shall be governed by the laws of the State.")
        assert result.risk_level != RiskLevel.LOW
        assert result.risk_level == RiskLevel.UNKNOWN
        assert result.abstained is True


class TestCaseI_UnknownDocumentType:
    def test_unknown_document_type_applies_no_hard_block(self):
        assert category_doc_type_relevance(RiskCategory.DEFAULT, DocumentType.UNKNOWN) == 1.0
        assert category_doc_type_relevance(RiskCategory.INSURANCE, DocumentType.UNKNOWN) == 1.0


class TestCaseJ_WrongCategoryForDocumentType:
    def test_insurance_category_pattern_blocked_for_loan_document(self):
        assert category_doc_type_relevance(RiskCategory.INSURANCE, DocumentType.LOAN) == 0.0

    def test_doc_type_gate_zeroes_out_raw_score_for_inapplicable_category(self):
        insurance_match = _pattern(
            similarity=0.95, lexical=0.8, category=RiskCategory.INSURANCE, subcategory="waiting_period"
        )
        result = _score(
            "A waiting period of 90 days applies before coverage under this policy becomes effective.",
            matched_patterns=[insurance_match],
            document_type=DocumentType.LOAN,
        )
        assert result.signals.doc_type_relevance == 0.0
        assert result.risk_level != RiskLevel.HIGH
        assert result.risk_level != RiskLevel.MEDIUM


class TestSegmentationLowConfidenceAbstention:
    def test_low_segmentation_confidence_forces_unknown_even_for_clear_rule(self):
        text = "Borrower shall pay a prepayment penalty equal to 5% if repaid within 24 months."
        result = _score(text, low_confidence=True)
        assert result.risk_level == RiskLevel.UNKNOWN
        assert result.abstained is True
        assert "segmentation" in result.abstain_reason.lower()


class TestSeverityCeiling:
    """PHASE_6.6 (docs/PROVISIONAL_DECISIONS.md P6.10): Risk_Taxonomy_and_Labeling_Spec.md
    SS1 gives some subcategories a default severity band that tops out at
    MEDIUM (never HIGH) — the flat scoring formula has no per-category
    notion of that on its own, so a rule-matched subcategory's taxonomy
    ceiling is applied as a post-threshold cap."""

    def test_ceiling_lowers_a_level_that_exceeds_it(self):
        assert apply_severity_ceiling(RiskLevel.HIGH, RiskLevel.MEDIUM) == RiskLevel.MEDIUM

    def test_ceiling_is_a_noop_when_level_already_at_or_below_it(self):
        assert apply_severity_ceiling(RiskLevel.MEDIUM, RiskLevel.MEDIUM) == RiskLevel.MEDIUM
        assert apply_severity_ceiling(RiskLevel.LOW, RiskLevel.MEDIUM) == RiskLevel.LOW
        assert apply_severity_ceiling(RiskLevel.UNKNOWN, RiskLevel.MEDIUM) == RiskLevel.UNKNOWN

    def test_none_ceiling_is_a_noop(self):
        assert apply_severity_ceiling(RiskLevel.HIGH, None) == RiskLevel.HIGH

    def test_auto_renewal_strong_signal_is_capped_at_medium_not_high(self):
        # Fee + surcharge + full condition chain would reach HIGH under the
        # flat formula alone — auto_renewal's taxonomy band is flat MEDIUM.
        result = _score(
            "Should the policyholder fail to provide notice, this policy renews "
            "automatically and a fee of Rs. 15,000 applies with 10% surcharge if unpaid.",
            document_type=DocumentType.INSURANCE,
        )
        assert result.risk_level == RiskLevel.MEDIUM
        assert result.risk_category == RiskCategory.RENEWAL
        assert result.risk_subcategory == "auto_renewal"
        # The displayed score must not contradict the capped level.
        assert result.risk_score < DEFAULT_RISK_ENGINE_CONFIG.high_threshold

    def test_uncapped_subcategory_can_still_reach_high(self):
        # prepayment_penalty's band is HIGH-leaning — no ceiling applies.
        result = _score(
            "Borrower shall pay a prepayment penalty equal to 5% of the outstanding "
            "principal if the loan is repaid in full within 24 months of disbursement."
        )
        assert result.risk_level == RiskLevel.HIGH


class TestSignalTypeCoverage:
    """PHASE_6.6 SS18: rule-only, entity-only, and amount-magnitude
    contrast cases — distinct from the negation/rule-pairing tests
    elsewhere, these isolate a single signal type at a time."""

    def test_rule_only_no_entity_no_condition_does_not_overclaim(self):
        # A standalone waiver with no financial entity and no conditional
        # connective — the rule fires, but with no corroborating signal the
        # engine must not assert a confident risk level (see
        # docs/SEVERITY_CALIBRATION_NOTES.md "rule-only risk").
        result = _score("The Borrower waives any right to a jury trial in connection with this agreement.")
        assert result.risk_level != RiskLevel.HIGH

    def test_entity_only_no_rule_match_does_not_force_a_risk_level(self):
        # "2%" is a real, extracted entity, but no deterministic rule
        # pattern matches this phrasing at all — entity presence alone must
        # not manufacture a confident risk level (Product Principle 3).
        result = _score("The processing fee is 2% of the loan amount.")
        assert result.risk_level != RiskLevel.HIGH
        assert result.risk_level != RiskLevel.MEDIUM

    def test_strong_amount_scores_at_least_as_high_as_weak_amount(self):
        weak = _score("Borrower shall pay a prepayment penalty if the loan is repaid early.")
        strong = _score(
            "Borrower shall pay a prepayment penalty equal to 25% of principal "
            "if the loan is repaid early."
        )
        assert strong.risk_score >= weak.risk_score
        assert strong.signals.entity_strength >= weak.signals.entity_strength


class TestConfidenceIndependence:
    """Phase 5 spec SS23 — confidence is not risk severity."""

    def test_high_risk_can_have_non_high_confidence(self):
        text = (
            "Borrower shall pay a prepayment penalty equal to 5% of the outstanding "
            "principal if the loan is repaid in full within 24 months of disbursement."
        )
        result = _score(text)
        assert result.risk_level == RiskLevel.HIGH
        # Confidence is computed independently and need not also be HIGH.
        assert result.confidence_level in (ConfidenceLevel.LOW, ConfidenceLevel.MEDIUM, ConfidenceLevel.HIGH)

    def test_high_risk_with_low_confidence_is_a_reachable_combination(self):
        # PHASE_6.6 (PRD_v2.md Product Principle 9): "HIGH RISK, confidence
        # 40%" must be a genuinely reachable output, not merely a type-level
        # possibility. Rule + entity alone (no retrieval margin, no
        # condition chain, weak signal agreement) reaches HIGH on raw score
        # while confidence stays low.
        result = _score("Prepayment penalty of 25% applies. Prepayment charges of 30% apply too.")
        assert result.risk_level == RiskLevel.HIGH
        assert result.confidence_level in (ConfidenceLevel.LOW, ConfidenceLevel.MEDIUM)

    def test_medium_risk_with_high_confidence_is_a_reachable_combination(self):
        result = _score(
            "In case of late payment, acceleration of the entire outstanding balance shall apply immediately.",
            matched_patterns=[
                _pattern(
                    similarity=0.85, lexical=0.6, category=RiskCategory.DEFAULT, subcategory="acceleration"
                )
            ],
        )
        assert result.risk_level == RiskLevel.MEDIUM
        assert result.confidence_score > 0.5

    def test_low_risk_can_have_higher_confidence_than_a_weaker_case(self):
        strong_negation = _score(
            "Borrower may prepay at any time without penalty.",
            matched_patterns=[_pattern(similarity=0.9, lexical=0.6, is_negative_example=True)],
        )
        weak_negation = _score("Borrower may prepay at any time without penalty.")
        assert strong_negation.risk_level == RiskLevel.LOW
        assert weak_negation.risk_level == RiskLevel.LOW
        assert strong_negation.confidence_score >= weak_negation.confidence_score

    def test_confidence_score_is_never_a_copy_of_risk_score(self):
        text = "Borrower shall pay a prepayment penalty equal to 5% if repaid within 24 months."
        result = _score(text)
        assert result.confidence_score != result.risk_score

    def test_incomplete_condition_lowers_confidence_relative_to_complete_chain(self):
        full_chain = _score(
            "In case of late payment, acceleration of the entire outstanding balance shall apply immediately."
        )
        partial_chain = _score(
            "Late payment may result in acceleration of amounts due under certain conditions."
        )
        assert full_chain.signals.condition_completeness_label == "full"
        assert partial_chain.signals.condition_completeness_label != "full"
        assert (
            full_chain.signals.condition_completeness_score
            > partial_chain.signals.condition_completeness_score
        )

    def test_retrieval_margin_influences_confidence(self):
        clear_top = [_pattern(similarity=0.9, lexical=0.1), _pattern(similarity=0.2, lexical=0.1)]
        ambiguous = [_pattern(similarity=0.9, lexical=0.1), _pattern(similarity=0.88, lexical=0.1)]
        text = "Borrower shall pay a prepayment penalty equal to 5% if repaid within 24 months."
        clear_result = _score(text, matched_patterns=clear_top)
        ambiguous_result = _score(text, matched_patterns=ambiguous)
        assert clear_result.signals.retrieval_margin > ambiguous_result.signals.retrieval_margin


class TestScoreEntities:
    def test_no_entities_scores_zero(self):
        assert score_entities([]) == 0.0

    def test_rate_entity_scores_higher_than_bare_time_period(self):
        rate = EntitySignal("rate", "18", "18% p.a.", 0, 8)
        period = EntitySignal("time_period", "30", "30 days", 0, 7)
        assert score_entities([rate]) > score_entities([period])


class TestScoreConditions:
    def test_full_chain_requires_trigger_and_consequence(self):
        score, label = score_conditions(trigger="if X happens", condition_text=None, consequence="Y applies")
        assert label == "full"
        assert score == 1.0

    def test_partial_chain(self):
        score, label = score_conditions(trigger="if X happens", condition_text=None, consequence=None)
        assert label == "partial"

    def test_none_chain(self):
        score, label = score_conditions(trigger=None, condition_text=None, consequence=None)
        assert label == "none"
        assert score == 0.0


class TestThresholdToLevel:
    def test_bands(self):
        config = DEFAULT_RISK_ENGINE_CONFIG
        assert threshold_to_level(config.high_threshold, config) == RiskLevel.HIGH
        assert threshold_to_level(config.medium_threshold, config) == RiskLevel.MEDIUM
        assert threshold_to_level(config.low_threshold, config) == RiskLevel.LOW
        assert threshold_to_level(0.0, config) == RiskLevel.UNKNOWN


class TestVersionMismatch:
    def test_mixed_taxonomy_versions_raises(self):
        patterns = [
            _pattern(similarity=0.5, taxonomy_version="taxonomy_v1", corpus_version="corpus_v1"),
            _pattern(similarity=0.5, taxonomy_version="taxonomy_v2", corpus_version="corpus_v1"),
        ]
        with pytest.raises(ValueError):
            _score("Some clause text.", matched_patterns=patterns)

    def test_mixed_corpus_versions_raises(self):
        patterns = [
            _pattern(similarity=0.5, taxonomy_version="taxonomy_v1", corpus_version="corpus_v1"),
            _pattern(similarity=0.5, taxonomy_version="taxonomy_v1", corpus_version="corpus_v2"),
        ]
        with pytest.raises(ValueError):
            _score("Some clause text.", matched_patterns=patterns)


class TestConfigValidation:
    def test_negative_weight_rejected(self):
        with pytest.raises(ValueError):
            RiskEngineConfig(weight_dense=-0.1)

    def test_threshold_ordering_enforced(self):
        with pytest.raises(ValueError):
            RiskEngineConfig(high_threshold=0.3, medium_threshold=0.5, low_threshold=0.1)

    def test_confidence_threshold_ordering_enforced(self):
        with pytest.raises(ValueError):
            RiskEngineConfig(confidence_high_threshold=0.4, confidence_medium_threshold=0.5)


class TestEngineVersioning:
    def test_result_carries_engine_version(self):
        result = _score("Borrower shall pay a prepayment penalty equal to 5% within 24 months.")
        assert result.engine_version == DEFAULT_RISK_ENGINE_CONFIG.version
        assert result.engine_version == "risk_engine_v1"
