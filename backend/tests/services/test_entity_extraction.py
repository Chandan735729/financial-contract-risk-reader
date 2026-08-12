"""Financial entity extraction tests — Phase 4 spec SS18.

All clause text is synthetic, written for this test suite only.
"""

from __future__ import annotations

from app.services.entity_extraction_service import extract_financial_entities


def _types(text: str) -> list[str]:
    return [e.entity_type for e in extract_financial_entities(text)]


def _raw_texts(text: str) -> list[str]:
    return [e.raw_text for e in extract_financial_entities(text)]


class TestPercentages:
    def test_plain_percentage(self):
        entities = extract_financial_entities("Borrower shall pay a fee equal to 5% of principal.")
        assert len(entities) == 1
        assert entities[0].entity_type == "percentage"
        assert entities[0].value == "5"
        assert entities[0].unit == "%"
        assert entities[0].raw_text == "5%"

    def test_decimal_percentage(self):
        entities = extract_financial_entities("A rate of 2.5% applies.")
        assert entities[0].value == "2.5"
        assert entities[0].raw_text == "2.5%"

    def test_percentage_with_per_annum_abbreviation_is_rate(self):
        entities = extract_financial_entities("Interest accrues at 18% p.a. on the balance.")
        assert len(entities) == 1
        assert entities[0].entity_type == "rate"
        assert entities[0].value == "18"
        assert entities[0].raw_text == "18% p.a."

    def test_percentage_with_per_month_is_rate(self):
        entities = extract_financial_entities("A late fee of 2% per month applies to overdue amounts.")
        rate_entities = [e for e in entities if e.entity_type == "rate"]
        assert len(rate_entities) == 1
        assert rate_entities[0].raw_text == "2% per month"

    def test_percentage_range_extracts_both_sides_independently(self):
        entities = extract_financial_entities("The rate ranges from 5% to 10% depending on tenure.")
        percentages = [e for e in entities if e.entity_type == "percentage"]
        assert {e.value for e in percentages} == {"5", "10"}


class TestAmounts:
    def test_rupee_symbol_amount(self):
        entities = extract_financial_entities("The processing fee is ₹10,000 payable upfront.")
        amounts = [e for e in entities if e.entity_type in ("amount", "fee")]
        assert len(amounts) == 1
        assert amounts[0].value == "10000"
        assert amounts[0].unit == "₹"
        assert amounts[0].raw_text == "₹10,000"

    def test_rs_dot_prefix_amount(self):
        entities = extract_financial_entities("Borrower shall pay Rs.500 as a late charge.")
        assert any(e.value == "500" for e in entities)

    def test_rs_with_space_amount(self):
        entities = extract_financial_entities("Borrower shall pay Rs. 10,000 within 30 days.")
        amount_entities = [e for e in entities if e.entity_type in ("amount", "fee")]
        assert amount_entities[0].value == "10000"

    def test_dollar_amount_supported(self):
        entities = extract_financial_entities("A fee of $500 applies for early termination.")
        assert any(e.value == "500" and e.unit == "$" for e in entities)

    def test_decimal_amount(self):
        entities = extract_financial_entities("The charge is ₹1999.50 per annum.")
        amounts = [e for e in entities if e.entity_type in ("amount", "fee")]
        assert amounts[0].value == "1999.50"

    def test_amount_near_fee_keyword_classified_as_fee(self):
        entities = extract_financial_entities("A late payment fee of ₹500 applies.")
        fee_entities = [e for e in entities if e.entity_type == "fee"]
        assert len(fee_entities) == 1
        assert fee_entities[0].value == "500"
        assert fee_entities[0].extraction_confidence < 1.0

    def test_amount_without_fee_context_classified_as_amount(self):
        entities = extract_financial_entities("The loan principal is ₹50,000.")
        amount_entities = [e for e in entities if e.entity_type == "amount"]
        assert len(amount_entities) == 1
        assert amount_entities[0].extraction_confidence == 1.0

    def test_word_form_amount_is_unsupported(self):
        # "ten thousand rupees" — explicitly documented as unsupported
        # (Phase 4 spec SS18 permits this).
        entities = extract_financial_entities("Borrower shall pay ten thousand rupees within 30 days.")
        assert not any(e.entity_type in ("amount", "fee") for e in entities)


class TestTimePeriods:
    def test_days(self):
        entities = extract_financial_entities("Payment is due within 30 days of invoice.")
        time_entities = [e for e in entities if e.entity_type == "time_period"]
        assert len(time_entities) == 1
        assert time_entities[0].value == "30"
        assert time_entities[0].unit == "days"
        assert time_entities[0].raw_text == "30 days"

    def test_months_plural_preserved(self):
        entities = extract_financial_entities("This policy renews after 12 months unless cancelled.")
        time_entities = [e for e in entities if e.entity_type == "time_period"]
        assert time_entities[0].raw_text == "12 months"
        assert time_entities[0].unit == "months"

    def test_singular_month(self):
        entities = extract_financial_entities("A grace period of 1 month applies.")
        time_entities = [e for e in entities if e.entity_type == "time_period"]
        assert time_entities[0].raw_text == "1 month"

    def test_years(self):
        entities = extract_financial_entities("Coverage continues for 5 years.")
        time_entities = [e for e in entities if e.entity_type == "time_period"]
        assert time_entities[0].raw_text == "5 years"


class TestMultipleAndUnrelatedNumbers:
    def test_multiple_entities_in_one_clause(self):
        entities = extract_financial_entities(
            "Borrower shall pay a 2% prepayment penalty on the ₹50,000 outstanding balance within 30 days."
        )
        types = {e.entity_type for e in entities}
        assert "percentage" in types
        assert "time_period" in types
        assert any(e.entity_type in ("amount", "fee") for e in entities)

    def test_numbers_unrelated_to_financial_entities_not_extracted(self):
        entities = extract_financial_entities(
            "This clause discusses Section 5.2 and clause 3 of the agreement."
        )
        assert entities == []

    def test_malformed_double_percent_still_extracts_leading_percentage(self):
        entities = extract_financial_entities("A malformed 5%% expression appears here.")
        assert any(e.raw_text == "5%" for e in entities)

    def test_malformed_reversed_percent_sign_not_extracted(self):
        entities = extract_financial_entities("A malformed %5 reversed expression appears here.")
        assert not any(e.raw_text == "%5" for e in entities)

    def test_empty_clause_returns_no_entities(self):
        assert extract_financial_entities("") == []

    def test_clause_with_no_financial_content_returns_no_entities(self):
        assert extract_financial_entities("The parties agree to act in good faith.") == []


class TestRawTextAndOffsetPreservation:
    def test_raw_text_is_exact_substring_of_source(self):
        text = "Borrower shall pay a prepayment penalty equal to 5% of the outstanding principal."
        for entity in extract_financial_entities(text):
            assert text[entity.start_char : entity.end_char] == entity.raw_text

    def test_entities_sorted_by_position(self):
        text = "A fee of ₹500 applies if repaid within 30 days at a rate of 5%."
        entities = extract_financial_entities(text)
        starts = [e.start_char for e in entities]
        assert starts == sorted(starts)
