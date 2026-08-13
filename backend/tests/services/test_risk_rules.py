"""Deterministic rule layer tests — Phase 5 spec SS15-16.

Covers all five named rules and, critically, negation: "prepayment penalty"
must read differently from "prepayment without penalty."
"""

from __future__ import annotations

from app.models.enums import RiskCategory, RiskLevel
from app.services.risk_rules import evaluate_rules, subcategory_severity_ceiling


def _polarities(text: str, rule_id: str) -> list[str]:
    return [m.polarity for m in evaluate_rules(text) if m.rule_id == rule_id]


class TestSeverityCeilingLookup:
    """PHASE_6.6 (docs/PROVISIONAL_DECISIONS.md P6.10)."""

    def test_flat_medium_subcategories_have_a_medium_ceiling(self):
        for subcategory in ("auto_renewal", "waiting_period", "deductible", "renewal_fee"):
            assert subcategory_severity_ceiling(subcategory) == RiskLevel.MEDIUM

    def test_medium_high_banded_subcategories_have_no_ceiling(self):
        for subcategory in ("prepayment_penalty", "arbitration", "acceleration", "cross_default"):
            assert subcategory_severity_ceiling(subcategory) is None

    def test_unknown_subcategory_has_no_ceiling(self):
        assert subcategory_severity_ceiling("not_a_real_subcategory") is None

    def test_none_subcategory_has_no_ceiling(self):
        assert subcategory_severity_ceiling(None) is None


class TestPositivePairings:
    def test_arbitration_waiver(self):
        matches = evaluate_rules(
            "Any dispute shall be resolved through binding arbitration, and the parties waive any right to a jury trial."
        )
        hit = [m for m in matches if m.rule_id == "arbitration_waiver"]
        assert len(hit) == 1
        assert hit[0].polarity == "positive"
        assert hit[0].risk_category == RiskCategory.LOSS_OF_RIGHTS

    def test_prepayment_penalty(self):
        matches = evaluate_rules("Borrower shall pay a prepayment penalty of 5% if repaid early.")
        hit = [m for m in matches if m.rule_id == "prepayment_penalty"]
        assert len(hit) == 1
        assert hit[0].polarity == "positive"
        assert hit[0].risk_category == RiskCategory.FINANCIAL_COST

    def test_auto_renewal_notice(self):
        matches = evaluate_rules("This policy renews automatically unless 30 days notice is given.")
        hit = [m for m in matches if m.rule_id == "auto_renewal_notice"]
        assert len(hit) == 1
        assert hit[0].risk_category == RiskCategory.RENEWAL

    def test_missed_payment_acceleration(self):
        matches = evaluate_rules(
            "Upon a missed payment, the entire outstanding balance shall become immediately due through acceleration."
        )
        hit = [m for m in matches if m.rule_id == "missed_payment_acceleration"]
        assert len(hit) == 1
        assert hit[0].polarity == "positive"
        assert hit[0].risk_category == RiskCategory.DEFAULT

    def test_early_termination_fee(self):
        matches = evaluate_rules("An early termination fee applies if this agreement ends before the term.")
        hit = [m for m in matches if m.rule_id == "early_termination_fee"]
        assert len(hit) == 1
        assert hit[0].risk_category == RiskCategory.TERMINATION


class TestNegation:
    def test_prepayment_without_penalty_is_negative(self):
        assert _polarities("Borrower may prepay at any time without penalty.", "prepayment_penalty") == [
            "negative"
        ]

    def test_no_additional_fee_is_negative(self):
        assert _polarities(
            "Early termination is permitted with no additional fee.", "early_termination_fee"
        ) == ["negative"]

    def test_unless_before_the_pairing_is_negative(self):
        # "unless" appears before both terms — still within the negation
        # window relative to the matched pairing.
        assert _polarities(
            "Unless stated otherwise, no prepayment penalty applies to this loan.", "prepayment_penalty"
        ) == ["negative"]

    def test_positive_case_has_no_negation_cue_nearby(self):
        assert _polarities(
            "Borrower shall pay a prepayment penalty equal to 2% of principal.", "prepayment_penalty"
        ) == ["positive"]

    def test_waiver_word_does_not_self_negate_arbitration_rule(self):
        # "waive"/"waiver" must never be treated as a negation cue — it is
        # the rule's own positive secondary term.
        assert _polarities(
            "The parties agree that any dispute is subject to arbitration and hereby waive a jury trial.",
            "arbitration_waiver",
        ) == ["positive"]


class TestPhase65NewRules:
    """PHASE_6.5 (docs/PROVISIONAL_DECISIONS.md P6.6 item 5): 8 new rules
    closing zero-coverage taxonomy categories. Each covered with a
    positive, negative, and ambiguous (correctly-does-not-fire) example."""

    def test_insurance_exclusion_positive(self):
        assert _polarities(
            "Claims arising from pre-existing medical conditions are excluded from coverage under this policy.",
            "insurance_exclusion",
        ) == ["positive"]

    def test_insurance_exclusion_negative(self):
        assert _polarities(
            "This policy does not exclude coverage for pre-existing medical conditions.",
            "insurance_exclusion",
        ) == ["negative"]

    def test_insurance_exclusion_ambiguous_does_not_fire(self):
        assert _polarities("Exclusions are listed in Appendix B.", "insurance_exclusion") == []

    def test_insurance_waiting_period_positive(self):
        assert _polarities(
            "A waiting period of 90 days applies before coverage under this policy becomes effective.",
            "insurance_waiting_period",
        ) == ["positive"]

    def test_insurance_waiting_period_negative(self):
        assert _polarities(
            "There is no waiting period before coverage begins under this policy.",
            "insurance_waiting_period",
        ) == ["negative"]

    def test_insurance_waiting_period_ambiguous_does_not_fire(self):
        assert (
            _polarities(
                "Waiting periods may apply depending on the type of claim.", "insurance_waiting_period"
            )
            == []
        )

    def test_insurance_deductible_positive(self):
        assert _polarities(
            "A deductible of Rs. 5,000 applies before coverage begins under this policy.",
            "insurance_deductible",
        ) == ["positive"]

    def test_insurance_deductible_negative(self):
        assert _polarities(
            "This policy has no deductible applicable to covered claims.", "insurance_deductible"
        ) == ["negative"]

    def test_insurance_deductible_ambiguous_does_not_fire(self):
        assert (
            _polarities("Deductible terms are described in the policy schedule.", "insurance_deductible")
            == []
        )

    def test_interest_rate_change_positive(self):
        assert _polarities(
            "The interest rate shall increase by 2% per annum if the borrower misses "
            "two consecutive installments.",
            "interest_rate_change",
        ) == ["positive"]

    def test_interest_rate_change_negative(self):
        assert _polarities(
            "The interest rate will not change during the term of this loan.", "interest_rate_change"
        ) == ["negative"]

    def test_interest_rate_change_ambiguous_does_not_fire(self):
        assert (
            _polarities("Interest rate terms are subject to the bank's policy.", "interest_rate_change") == []
        )

    def test_standalone_rights_waiver_positive(self):
        assert _polarities(
            "The Borrower waives any right to a jury trial in connection with this agreement.",
            "standalone_rights_waiver",
        ) == ["positive"]

    def test_standalone_rights_waiver_negative(self):
        assert _polarities(
            "No right under this agreement is waived by either party.", "standalone_rights_waiver"
        ) == ["negative"]

    def test_standalone_rights_waiver_ambiguous_does_not_fire(self):
        assert (
            _polarities(
                "Certain statutory protections may or may not be waived depending on jurisdiction.",
                "standalone_rights_waiver",
            )
            == []
        )

    def test_cross_default_positive(self):
        assert _polarities(
            "A default under any other loan or credit agreement shall constitute a "
            "cross-default under this agreement, entitling the lender to accelerate.",
            "cross_default",
        ) == ["positive"]

    def test_cross_default_negative(self):
        assert _polarities(
            "This loan does not contain a cross-default provision linked to other agreements.",
            "cross_default",
        ) == ["negative"]

    def test_cross_default_ambiguous_does_not_fire(self):
        assert (
            _polarities(
                "Cross-default provisions may apply as set forth elsewhere in this agreement.",
                "cross_default",
            )
            == []
        )

    def test_renewal_fee_positive(self):
        assert _polarities(
            "A renewal fee of Rs. 1,500 is payable upon each policy renewal.", "renewal_fee"
        ) == ["positive"]

    def test_renewal_fee_negative(self):
        assert _polarities("No renewal fee is charged for this membership.", "renewal_fee") == ["negative"]

    def test_renewal_fee_ambiguous_does_not_fire(self):
        assert (
            _polarities("Renewal fee schedules are published separately by the insurer.", "renewal_fee") == []
        )

    def test_unilateral_termination_positive(self):
        assert _polarities(
            "The Lender may terminate this agreement at its sole discretion at any time without cause.",
            "unilateral_termination",
        ) == ["positive"]

    def test_unilateral_termination_negative(self):
        assert _polarities(
            "Termination of this agreement requires the mutual written consent of both parties "
            "and may not occur unilaterally.",
            "unilateral_termination",
        ) == ["negative"]

    def test_unilateral_termination_ambiguous_does_not_fire(self):
        assert (
            _polarities(
                "The agreement may be terminated under certain conditions at the discretion of the parties.",
                "unilateral_termination",
            )
            == []
        )


class TestPhase65BroadenedExistingRules:
    """Generalized phrasing added to existing rules, not TEST-string
    matches (see condition on each rule's docstring comment)."""

    def test_prepayment_penalty_payoff_ahead_of_schedule_phrasing(self):
        assert _polarities(
            "Should the borrower choose to settle the loan ahead of schedule, a 4% early payoff fee applies.",
            "prepayment_penalty",
        ) == ["positive"]

    def test_early_termination_fee_generic_terminate_agreement_phrasing(self):
        assert _polarities(
            "Either party may terminate this agreement with 60 days written notice, "
            "without cause and without penalty.",
            "early_termination_fee",
        ) == ["negative"]

    def test_auto_renewal_annually_with_cancellation_phrasing(self):
        assert _polarities(
            "This insurance policy renews annually unless the insured cancels in writing "
            "at least 15 days before the renewal date.",
            "auto_renewal_notice",
        ) == ["positive"]


class TestConditionalExceptions:
    """PHASE_6.5 (docs/PROVISIONAL_DECISIONS.md P6.9): "no X unless Y" is a
    conditional carve-out re-establishing risk, not confirmed-safe negation."""

    def test_no_x_unless_y_is_conditional_not_negative(self):
        assert _polarities(
            "No prepayment penalty applies unless the loan is repaid within 12 months.",
            "prepayment_penalty",
        ) == ["conditional"]

    def test_no_x_except_y_is_conditional_not_negative(self):
        assert _polarities(
            "No early termination fee is charged except when the tenant vacates before the lease term ends.",
            "early_termination_fee",
        ) == ["conditional"]

    def test_neither_party_waives_is_negative_not_positive(self):
        # docs/PROVISIONAL_DECISIONS.md P6.6 item 3: "neither" was missing
        # from the negation cue set; "neither...waives" was misread as a
        # positive arbitration_waiver hit.
        assert _polarities(
            "Any dispute may optionally proceed to arbitration, but neither party waives any other legal right.",
            "arbitration_waiver",
        ) == ["negative"]

    def test_unrelated_unless_in_a_later_sentence_does_not_flip_to_conditional(self):
        # The exception-marker search must not cross a sentence boundary —
        # an "unless" in a separate, unrelated sentence must not turn an
        # unambiguous negative match into a conditional one.
        assert _polarities(
            "No prepayment penalty applies to standard payments. "
            "Unless otherwise stated in Appendix C, other rules govern unrelated matters entirely here.",
            "prepayment_penalty",
        ) == ["negative"]

    def test_unless_preceding_the_pairing_stays_negative(self):
        # "unless" appearing *before* the negated pairing (a preface, not a
        # trailing carve-out on this specific pairing) is unchanged
        # (regression guard for TestNegation.test_unless_before_the_pairing_is_negative).
        assert _polarities(
            "Unless stated otherwise, no prepayment penalty applies to this loan.", "prepayment_penalty"
        ) == ["negative"]


class TestNoMatch:
    def test_primary_term_alone_does_not_fire(self):
        matches = evaluate_rules("The borrower may prepay the loan at his discretion.")
        assert not any(m.rule_id == "prepayment_penalty" for m in matches)

    def test_unrelated_text_fires_nothing(self):
        assert evaluate_rules("This agreement is governed by the laws of the State.") == []

    def test_secondary_term_far_outside_proximity_window_does_not_fire(self):
        filler = " lorem ipsum dolor sit amet consectetur adipiscing elit " * 5
        text = f"Borrower may prepay early.{filler}A separate penalty schedule appears elsewhere."
        matches = [m for m in evaluate_rules(text) if m.rule_id == "prepayment_penalty"]
        assert matches == []


class TestEvidenceSpanIntegrity:
    def test_evidence_text_is_exact_substring_of_source(self):
        text = "Borrower shall pay a prepayment penalty equal to 2% of principal."
        for match in evaluate_rules(text):
            assert text[match.start_char : match.end_char] == match.evidence_text

    def test_at_most_one_match_per_rule(self):
        text = (
            "Borrower shall pay a prepayment penalty. If the borrower prepays again, "
            "another prepayment penalty applies."
        )
        matches = [m for m in evaluate_rules(text) if m.rule_id == "prepayment_penalty"]
        assert len(matches) == 1
