"""Trigger/condition/consequence extraction tests — Phase 4 spec SS19.

All clause text is synthetic, written for this test suite only.
"""

from __future__ import annotations

from app.services.condition_extraction_service import extract_condition


class TestClearChains:
    def test_complete_chain_with_condition_qualifier(self):
        r = extract_condition(
            "If the borrower repays early within the first 12 months, a 5% prepayment charge applies."
        )
        assert r.trigger == "If the borrower repays early"
        assert r.condition == "within the first 12 months"
        assert r.consequence == "a 5% prepayment charge applies"
        assert r.affected_party == "the borrower"

    def test_complete_chain_second_example(self):
        r = extract_condition(
            "If any installment remains unpaid for more than 30 days, "
            "the lender may accelerate the outstanding balance."
        )
        assert r.trigger == "If any installment remains unpaid"
        assert r.condition == "for more than 30 days"
        assert r.consequence == "the lender may accelerate the outstanding balance"
        assert r.affected_party == "the lender"

    def test_clear_trigger_and_consequence_no_qualifier(self):
        r = extract_condition("If the borrower defaults, the lender may accelerate the balance.")
        assert r.trigger == "If the borrower defaults"
        assert r.condition is None
        assert r.consequence == "the lender may accelerate the balance"


class TestPartialChains:
    def test_missing_consequence_short_fragment_not_kept(self):
        # A trailing fragment too short to be a real consequence is dropped
        # rather than kept as noise.
        r = extract_condition("If the borrower defaults, then so.")
        assert r.trigger is not None
        assert r.consequence is None

    def test_trigger_without_comma_still_produces_a_result(self):
        r = extract_condition("When the claim is approved the insurer shall pay within 30 days.")
        assert r.trigger is not None
        assert "claim is approved" in r.trigger

    def test_missing_trigger_when_no_connective_present(self):
        r = extract_condition("The Borrower shall repay the loan in accordance with the schedule.")
        assert r.trigger is None
        assert r.condition is None
        assert r.consequence is None


class TestAmbiguousLanguageNeverInvented:
    def test_vague_circumstance_language_produces_no_trigger(self):
        r = extract_condition("This fee may apply under certain circumstances.")
        assert r.trigger is None
        assert r.condition is None
        assert r.consequence is None

    def test_negative_example_produces_no_trigger(self):
        r = extract_condition("Borrower may make additional principal payments at any time without penalty.")
        assert r.trigger is None
        assert r.condition is None

    def test_short_boilerplate_sentence_produces_no_chain(self):
        r = extract_condition("This agreement is governed by the laws of India.")
        assert r.trigger is None


class TestUnlessExceptNegativeConditions:
    def test_unless_marker_flagged_as_negative_trigger(self):
        r = extract_condition(
            "Unless the policyholder provides 30 days notice, the policy renews automatically."
        )
        assert r.is_negative_trigger is True
        assert r.trigger is not None
        assert r.consequence == "the policy renews automatically"

    def test_except_where_marker_detected(self):
        r = extract_condition("Except where the borrower has defaulted, no penalty shall apply.")
        assert r.is_negative_trigger is True
        assert r.trigger is not None

    def test_if_marker_preferred_over_unless_when_both_absent(self):
        # Positive trigger markers are searched first; only fall back to
        # unless/except when no positive marker exists at all.
        r = extract_condition("If the borrower defaults, the lender may terminate.")
        assert r.is_negative_trigger is False


class TestOrAndConditions:
    def test_or_condition_captured_as_single_trigger_span(self):
        r = extract_condition(
            "If the borrower fails to pay or breaches a material term, the lender may terminate."
        )
        assert r.trigger is not None
        assert "or breaches" in r.trigger
        assert r.consequence == "the lender may terminate"

    def test_and_condition_captured(self):
        r = extract_condition(
            "If the borrower defaults and fails to cure within 10 days, acceleration applies."
        )
        assert r.trigger is not None
        assert "and fails to cure" in r.trigger or (r.condition is not None and "cure" in r.condition)


class TestMultipleAndNestedConditions:
    def test_multiple_trigger_markers_uses_first_one(self):
        r = extract_condition("If the borrower defaults, the lender may terminate if notice has been given.")
        assert r.trigger == "If the borrower defaults"

    def test_nested_condition_qualifier_inside_trigger_span(self):
        r = extract_condition(
            "If the borrower remains in default for more than 60 days, foreclosure proceedings may begin."
        )
        assert r.trigger == "If the borrower remains in default"
        assert r.condition == "for more than 60 days"
        assert r.consequence == "foreclosure proceedings may begin"


class TestCrossReferenceLanguage:
    def test_cross_reference_does_not_prevent_extraction(self):
        r = extract_condition(
            "If a default occurs as described in Section 5.1, the consequence in Section 6 shall apply."
        )
        assert r.trigger is not None
        assert r.consequence is not None

    def test_cross_reference_alone_produces_no_chain(self):
        r = extract_condition("See Section 5.1 for the definition of default.")
        assert r.trigger is None


class TestAffectedParty:
    def test_affected_party_detected_independently_of_trigger(self):
        r = extract_condition("The Borrower shall repay the loan in accordance with the schedule.")
        assert r.affected_party == "The Borrower"

    def test_no_affected_party_when_no_party_term_present(self):
        r = extract_condition("If the outstanding balance exceeds the credit limit, interest accrues.")
        assert r.affected_party is None

    def test_either_party_detected(self):
        r = extract_condition("Either party may terminate this agreement with 30 days notice.")
        assert r.affected_party == "Either party"


class TestNeverInventsFields:
    def test_empty_clause_returns_all_none(self):
        r = extract_condition("")
        assert r.trigger is None
        assert r.condition is None
        assert r.consequence is None
        assert r.affected_party is None

    def test_consequence_never_fabricated_when_absent(self):
        r = extract_condition("If the borrower defaults.")
        assert r.trigger is not None
        assert r.consequence is None
