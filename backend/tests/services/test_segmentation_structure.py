"""Structure-analysis signal tests — Phase 3 spec SS2.

Exercises `_classify_block` directly against hand-built `DocumentTextBlock`s
(no parser needed) to pin down numbering/heading pattern recognition
independent of PDF/DOCX extraction quirks.
"""

from __future__ import annotations

from typing import Any

from app.services.parsing.models import DocumentTextBlock
from app.services.segmentation_service import _classify_block


def _block(text: str, **overrides: Any) -> DocumentTextBlock:
    defaults: dict[str, Any] = {"text": text, "order": 0, "source_type": "pdf"}
    defaults.update(overrides)
    return DocumentTextBlock(**defaults)


class TestNumberingPatterns:
    def test_top_level_numeric(self):
        signal = _classify_block(_block("1. Borrower shall repay the loan in full."))
        assert signal.numbering_kind == "top_numeric"
        assert signal.numbering_value == "1"

    def test_multi_digit_top_level_numeric(self):
        signal = _classify_block(_block("23. This is a later numbered clause."))
        assert signal.numbering_kind == "top_numeric"
        assert signal.numbering_value == "23"

    def test_two_level_subsection(self):
        signal = _classify_block(_block("3.1 Interest shall accrue daily on the outstanding balance."))
        assert signal.numbering_kind == "sub_numeric"
        assert signal.numbering_value == "3.1"

    def test_three_level_subsection(self):
        signal = _classify_block(_block("1.1.1 A further nested condition applies to this subclause."))
        assert signal.numbering_kind == "sub_numeric"
        assert signal.numbering_value == "1.1.1"

    def test_lettered_subclause(self):
        signal = _classify_block(_block("(a) the Borrower fails to make a scheduled payment;"))
        assert signal.numbering_kind == "lettered"
        assert signal.numbering_value == "a"

    def test_roman_numeral_subclause(self):
        signal = _classify_block(_block("(iv) any other event of default specified herein."))
        assert signal.numbering_kind == "roman"
        assert signal.numbering_value == "iv"

    def test_single_letter_i_is_lettered_not_roman(self):
        # "(i)" alone is ambiguous (letter i vs. roman numeral one) —
        # disambiguated by length: single-char parenthetical is lettered.
        signal = _classify_block(_block("(i) a missed payment under this agreement;"))
        assert signal.numbering_kind == "lettered"

    def test_multi_char_roman_is_roman(self):
        signal = _classify_block(_block("(ii) a cross-default under any related agreement;"))
        assert signal.numbering_kind == "roman"

    def test_section_word(self):
        signal = _classify_block(_block("Section 3.2 governs early termination fees."))
        assert signal.numbering_kind == "section_word"
        assert signal.numbering_value == "3.2"

    def test_plain_prose_has_no_numbering(self):
        signal = _classify_block(_block("The parties agree to the terms set out below."))
        assert signal.numbering_kind is None

    def test_number_mid_sentence_is_not_numbering(self):
        # "at 2." appearing mid-sentence must not be mistaken for a clause
        # opener — numbering must anchor at the start of the block.
        signal = _classify_block(
            _block("The rate is capped at 2. This is still one sentence though unusual.")
        )
        assert signal.numbering_kind is None

    def test_decimal_amount_at_start_is_not_multi_level_numbering(self):
        # "2.5% interest applies" must not be misread as sub_numeric "2.5"
        # boundary — the multi-level regex requires a space-separated
        # continuation after the trailing dot-number, which a percentage
        # like "2.5%" does not have.
        signal = _classify_block(_block("2.5% interest applies to any overdue balance under this agreement."))
        assert signal.numbering_kind != "sub_numeric"


class TestHeadingDetection:
    def test_docx_explicit_heading_style_is_explicit_heading(self):
        signal = _classify_block(_block("Definitions", is_heading=True, style="Heading 1"))
        assert signal.is_explicit_heading is True
        assert signal.is_heading_like is True

    def test_docx_normal_style_is_not_heading(self):
        signal = _classify_block(_block("This is a normal body paragraph.", is_heading=False, style="Normal"))
        assert signal.is_explicit_heading is False
        assert signal.is_heading_like is False

    def test_pdf_bold_short_text_is_heading_like_but_not_explicit(self):
        signal = _classify_block(_block("Repayment Terms", is_bold=True))
        assert signal.is_heading_like is True
        assert signal.is_explicit_heading is False

    def test_pdf_bold_long_sentence_is_not_heading_like(self):
        long_text = (
            "The Borrower shall pay all amounts due under this Agreement in full "
            "and on time in accordance with the payment schedule set out in Schedule A."
        )
        signal = _classify_block(_block(long_text, is_bold=True))
        assert signal.is_heading_like is False

    def test_bold_sentence_ending_in_period_is_not_heading_like(self):
        signal = _classify_block(_block("This is a bold sentence.", is_bold=True))
        assert signal.is_heading_like is False

    def test_table_cell_is_never_heading_like_even_if_bold(self):
        signal = _classify_block(_block("Fee Type", is_bold=True, is_table_cell=True))
        assert signal.is_heading_like is False

    def test_table_cell_is_never_explicit_heading(self):
        signal = _classify_block(_block("Fee Type", is_heading=True, is_table_cell=True))
        assert signal.is_explicit_heading is False

    def test_list_item_is_not_treated_as_heading_even_if_bold(self):
        signal = _classify_block(_block("Important term", is_bold=True, is_list_item=True))
        assert signal.is_heading_like is False
