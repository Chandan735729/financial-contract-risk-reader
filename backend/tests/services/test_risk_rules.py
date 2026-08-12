"""Deterministic rule layer tests — Phase 5 spec SS15-16.

Covers all five named rules and, critically, negation: "prepayment penalty"
must read differently from "prepayment without penalty."
"""

from __future__ import annotations

from app.models.enums import RiskCategory
from app.services.risk_rules import evaluate_rules


def _polarities(text: str, rule_id: str) -> list[str]:
    return [m.polarity for m in evaluate_rules(text) if m.rule_id == rule_id]


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
