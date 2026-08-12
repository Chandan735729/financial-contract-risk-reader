"""End-to-end clause segmentation tests — Phase 3 spec SS13.

Each test is one of the twenty required scenarios. All content is synthetic
(tests/fixtures/segmentation_documents.py, tests/fixtures/synthetic_documents.py).
"""

from __future__ import annotations

from typing import Any

from app.services.parsing.docx_parser import parse_docx
from app.services.parsing.models import ParsedDocument
from app.services.parsing.pdf_parser import parse_pdf
from app.services.segmentation_service import segment_document, validate_invariants
from tests.fixtures.segmentation_documents import Paragraph, build_pdf_paragraphs
from tests.fixtures.synthetic_documents import build_docx


def _segment_pdf(paragraphs: list, **kwargs: Any):
    data = build_pdf_paragraphs(paragraphs, **kwargs)
    parsed = parse_pdf(data, max_pages=500, min_text_chars=1, min_avg_chars_per_page=1.0).document
    assert parsed is not None
    return parsed, segment_document(parsed)


def _segment_docx(items: list, include_table: bool = False):
    data = build_docx(items=items, include_table=include_table)
    parsed = parse_docx(data, max_items=5000, min_text_chars=1).document
    assert parsed is not None
    return parsed, segment_document(parsed)


# 1. simple numbered contract ------------------------------------------------
def test_simple_numbered_contract():
    parsed, result = _segment_pdf(
        [
            "1. Prepayment. Borrower may prepay the loan subject to a 2% penalty fee.",
            "2. Default. A missed payment constitutes default under this agreement.",
            "3. Termination. Either party may terminate with 30 days written notice.",
        ]
    )
    assert len(result.clauses) == 3
    assert [c.boundary_signal for c in result.clauses] == ["top_numeric"] * 3
    assert all(not c.low_confidence_flag for c in result.clauses)
    assert validate_invariants(parsed, result) == []


# 2. nested numbering ---------------------------------------------------------
def test_nested_numbering():
    parsed, result = _segment_pdf(
        [
            "1. Repayment. This section governs repayment of the loan.",
            "1.1 Borrower shall repay in 12 equal monthly instalments.",
            "1.2 Each instalment is due on the first business day of the month.",
            "2. Default. This section governs default.",
        ]
    )
    assert len(result.clauses) == 4
    assert [c.boundary_signal for c in result.clauses] == [
        "top_numeric",
        "sub_numeric",
        "sub_numeric",
        "top_numeric",
    ]
    assert validate_invariants(parsed, result) == []


# 3. lettered subclauses -------------------------------------------------------
def test_lettered_subclauses():
    parsed, result = _segment_pdf(
        [
            "5. Events of Default. Any of the following constitutes an event of default:",
            "(a) failure to make a scheduled payment within 10 days of the due date;",
            "(b) breach of any other material term of this agreement;",
            "(c) insolvency or bankruptcy of the Borrower.",
        ]
    )
    assert len(result.clauses) == 4
    assert result.clauses[1].boundary_signal == "lettered"
    assert result.clauses[2].boundary_signal == "lettered"
    assert result.clauses[3].boundary_signal == "lettered"
    assert validate_invariants(parsed, result) == []


# 4. headings without numbering ------------------------------------------------
def test_headings_without_numbering_docx():
    parsed, result = _segment_docx(
        [
            ("Heading 1", "Definitions"),
            ("Normal", "In this agreement, Borrower means the party receiving the loan."),
            ("Heading 1", "Repayment"),
            ("Normal", "The Borrower shall repay the loan in accordance with the schedule."),
        ]
    )
    assert len(result.clauses) == 2
    assert result.clauses[0].section_heading == "Definitions"
    assert result.clauses[1].section_heading == "Repayment"
    assert all(c.boundary_signal == "after_heading" for c in result.clauses)
    assert validate_invariants(parsed, result) == []


# 5. unstructured prose ---------------------------------------------------------
def test_unstructured_prose_no_numbering_or_headings():
    parsed, result = _segment_pdf(
        [
            "This agreement is entered into between the lender and the borrower.",
            "The borrower agrees to repay the amount borrowed over time.",
            "Both parties agree to act in good faith throughout the term.",
        ]
    )
    # No boundary signals at all -> everything merges into one fallback clause;
    # honestly reflects "we could not find structure" rather than guessing.
    assert len(result.clauses) == 1
    assert result.clauses[0].boundary_signal == "fallback"
    assert validate_invariants(parsed, result) == []


# 6. mixed formatting -----------------------------------------------------------
def test_mixed_formatting_numbered_and_lettered_and_headings():
    parsed, result = _segment_pdf(
        [
            Paragraph("LOAN AGREEMENT", bold=True),
            "1. Prepayment. Borrower may prepay subject to conditions below:",
            "(a) a 2% fee applies if repaid within 12 months;",
            "(b) no fee applies thereafter.",
            "2. Default. Any of the following is a default:",
            "(i) a missed payment;",
            "(ii) a breach of a material covenant.",
        ]
    )
    assert len(result.clauses) == 7
    signals = [c.boundary_signal for c in result.clauses]
    # "(i)" alone is single-character -> lettered (see
    # test_single_letter_i_is_lettered_not_roman); "(ii)" is multi-character -> roman.
    assert signals == [
        "heading_like",
        "top_numeric",
        "lettered",
        "lettered",
        "top_numeric",
        "lettered",
        "roman",
    ]
    assert validate_invariants(parsed, result) == []


# 7. multi-page clause ------------------------------------------------------------
def test_clause_spans_multiple_pages_without_boundary_on_page_break():
    # `insert_text` does not auto-wrap a single long string — a genuine
    # multi-page clause is many *separate* continuation paragraphs (no
    # numbering/heading of their own), which is also how a real PDF parser
    # actually splits a paragraph that crosses a page boundary.
    continuation = [
        f"This is synthetic filler sentence number {i} describing repayment obligations." for i in range(40)
    ]
    parsed, result = _segment_pdf(
        [
            "1. Repayment. This section describes repayment.",
            *continuation,
            "2. Default. A short default clause.",
        ]
    )
    assert parsed.page_count is not None and parsed.page_count >= 2
    assert len(result.clauses) == 2
    assert result.clauses[0].boundary_signal == "top_numeric"
    # Clause 1 starts on page 1 even though its text continues onto page 2 —
    # a page break alone must never create a new clause (Phase 3 spec SS4/SS7).
    assert result.clauses[0].page_number == 1
    assert len(result.clauses[0].raw_text) > 1000
    assert validate_invariants(parsed, result) == []


# 8. repeated header/footer --------------------------------------------------------
def test_repeated_header_and_footer_suppressed_across_pages():
    numbered_clauses = [
        f"{n}. Synthetic clause number {n}. This clause describes a minor administrative "
        "term relating to notices and correspondence under this synthetic agreement."
        for n in range(1, 40)
    ]
    parsed, result = _segment_pdf(
        numbered_clauses,
        header="CONFIDENTIAL — SYNTHETIC LOAN AGREEMENT",
        footer="Page X of Y synthetic footer",
    )
    assert parsed.page_count is not None and parsed.page_count >= 3
    heading_texts = {c.raw_text for c in result.clauses}
    assert not any("CONFIDENTIAL" in t for t in heading_texts)
    assert not any("Page X of Y" in t for t in heading_texts)
    assert len(result.clauses) == 39
    assert validate_invariants(parsed, result) == []


def test_lone_page_number_line_suppressed_even_on_single_page():
    parsed, result = _segment_pdf(
        ["Page 1 of 1", "1. Prepayment. A single clause on a single page document."]
    )
    assert len(result.clauses) == 1
    assert "Page 1 of 1" not in result.clauses[0].raw_text
    assert result.diagnostics is not None
    assert result.diagnostics.suppressed_block_count == 1


# 9. table-containing document -----------------------------------------------------
def test_table_containing_docx_preserves_cell_text_without_crashing():
    parsed, result = _segment_docx(
        [
            ("Heading 1", "Fee Schedule"),
            ("Normal", "The following fees apply under this agreement:"),
        ],
        include_table=True,
    )
    assert result.clauses  # did not crash, produced output
    all_text = " ".join(c.raw_text for c in result.clauses)
    assert "Fee Type" in all_text
    assert "$25 synthetic flat fee" in all_text
    assert validate_invariants(parsed, result) == []


# 10. DOCX heading styles -----------------------------------------------------------
def test_docx_heading_styles_captured_as_section_heading_not_clause_text():
    parsed, result = _segment_docx(
        [
            ("Heading 1", "Termination"),
            ("Normal", "1. Either party may terminate this agreement with 30 days notice."),
        ]
    )
    assert len(result.clauses) == 1
    assert result.clauses[0].section_heading == "Termination"
    assert "Termination" not in result.clauses[0].raw_text
    assert validate_invariants(parsed, result) == []


# 11. badly formatted PDF -------------------------------------------------------------
def test_badly_formatted_pdf_does_not_crash():
    parsed, result = _segment_pdf(
        [
            Paragraph("odd fragment", bold=True),
            "5. skip ahead",
            "(z) an unusual lettered marker",
            "Section 99.99 an unusual section reference",
            "just some trailing prose with no structure at all",
        ]
    )
    assert result.clauses  # produced *something*, did not raise
    assert validate_invariants(parsed, result) == []


# 12. very short document ------------------------------------------------------------
def test_very_short_document_single_clause():
    parsed, result = _segment_pdf(["1. Fee. A flat $10 fee applies."])
    assert len(result.clauses) == 1
    assert result.clauses[0].raw_text == "1. Fee. A flat $10 fee applies."
    assert validate_invariants(parsed, result) == []


# 13. very large clause -----------------------------------------------------------------
def test_very_large_clause_flagged_low_confidence():
    # Many unnumbered continuation paragraphs, all merging into one clause —
    # `insert_text` doesn't wrap a single giant string, so a large clause is
    # built the same way a real multi-page undifferentiated block would be.
    filler = [
        f"Synthetic filler sentence {i} about repayment terms and conditions herein." for i in range(150)
    ]
    parsed, result = _segment_pdf(["1. Everything. This clause covers all repayment terms.", *filler])
    assert len(result.clauses) == 1
    assert len(result.clauses[0].raw_text) >= 8000
    assert result.clauses[0].low_confidence_flag is True
    assert validate_invariants(parsed, result) == []


# 14. many tiny fragments -------------------------------------------------------------------
def test_many_tiny_fragments_triggers_low_confidence():
    fragments = [f"x{i}" for i in range(30)]  # no numbering, no headings, all tiny
    parsed, result = _segment_pdf(fragments)
    assert result.low_confidence_flag is True or all(c.low_confidence_flag for c in result.clauses)
    assert validate_invariants(parsed, result) == []


# 15. conflicting structural signals ---------------------------------------------------------
def test_inconsistent_numbering_flags_document_low_confidence():
    parsed, result = _segment_pdf(
        [
            "1. First clause with normal numbering.",
            "2. Second clause with normal numbering.",
            "9. A clause that jumps far ahead unexpectedly.",
            "3. A clause that jumps back down again.",
        ]
    )
    assert result.low_confidence_flag is True
    assert result.diagnostics is not None
    assert result.diagnostics.document_level_anomaly == "inconsistent_numbering"
    assert all(c.low_confidence_flag for c in result.clauses)
    assert validate_invariants(parsed, result) == []


# 16. empty/invalid parser result -------------------------------------------------------------
def test_empty_parsed_document_produces_no_clauses_not_a_crash():
    empty = ParsedDocument(source_type="pdf", blocks=())
    result = segment_document(empty)
    assert result.clauses == ()
    assert result.low_confidence_flag is True
    assert result.diagnostics is not None
    assert result.diagnostics.document_level_anomaly == "no_text_blocks"
    assert validate_invariants(empty, result) == []


# 17. document-order preservation --------------------------------------------------------------
def test_document_order_preserved():
    parsed, result = _segment_pdf(
        [f"{n}. Synthetic clause number {n} about a minor term." for n in range(1, 8)]
    )
    orders = [c.start_block_order for c in result.clauses]
    assert orders == sorted(orders)
    assert [c.clause_index for c in result.clauses] == list(range(len(result.clauses)))
    assert validate_invariants(parsed, result) == []


# 18. no accidental text duplication -------------------------------------------------------------
def test_no_accidental_text_duplication():
    parsed, result = _segment_pdf(
        [
            "1. Prepayment. Borrower may prepay subject to a 2% fee.",
            "2. Default. A missed payment constitutes default.",
        ]
    )
    texts = [c.raw_text for c in result.clauses]
    assert len(texts) == len(set(texts))
    d = result.diagnostics
    assert d is not None
    assert d.covered_chars + d.suppressed_chars + d.heading_metadata_chars == d.total_chars
    assert validate_invariants(parsed, result) == []


# 19. low-confidence segmentation ------------------------------------------------------------------
def test_low_confidence_segmentation_still_produces_usable_clauses():
    # Deliberately unstructured -> low confidence, but must still segment
    # (Phase 3 spec SS9: "Do not fail an otherwise readable document merely
    # because segmentation confidence is low").
    parsed, result = _segment_pdf(["some completely unstructured prose with no signals whatsoever"])
    assert len(result.clauses) == 1
    assert result.clauses[0].low_confidence_flag is True
    assert result.clauses[0].raw_text  # still has usable content


# 20. sequential clause indexes -------------------------------------------------------------------------
def test_sequential_clause_indexes():
    parsed, result = _segment_pdf([f"{n}. Clause number {n}." for n in range(1, 15)])
    assert [c.clause_index for c in result.clauses] == list(range(14))
    assert validate_invariants(parsed, result) == []
