"""Synthetic segmentation benchmark — Dataset_and_Evaluation_Spec.md SS4,
Phase 3 spec SS11.

**This is a synthetic, hand-authored benchmark for development and
regression-testing the segmentation harness itself — it is not a real-world
benchmark and the numbers it produces do not represent production accuracy
on messy real documents.** See docs/PROVISIONAL_DECISIONS.md "Phase 3:
segmentation evaluation is synthetic-only" and
Dataset_and_Evaluation_Spec.md SS4 for what a real benchmark requires
(independently annotated real-world documents, inter-annotator agreement
checking) — none of that applies here.

Each `BenchmarkCase` pairs a synthetic document with hand-computed gold
clause-boundary positions, expressed as `DocumentTextBlock.order` values —
computable by construction here because each case is built from a flat list
of (text, is_boundary) items with no header/footer (which would otherwise
shift block order relative to the input list).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.services.parsing.docx_parser import parse_docx
from app.services.parsing.models import ParsedDocument
from app.services.parsing.pdf_parser import parse_pdf
from tests.fixtures.segmentation_documents import Paragraph, build_pdf_paragraphs
from tests.fixtures.synthetic_documents import build_docx


@dataclass(frozen=True)
class BenchmarkCase:
    name: str
    category: str
    parsed: ParsedDocument
    gold_boundaries: frozenset[int]


def _pdf_case(
    name: str, category: str, items: list[tuple[Paragraph | str, bool]], **builder_kwargs: Any
) -> BenchmarkCase:
    paragraphs = [text for text, _ in items]
    gold = frozenset(i for i, (_, is_boundary) in enumerate(items) if is_boundary)
    data = build_pdf_paragraphs(paragraphs, **builder_kwargs)
    result = parse_pdf(data, max_pages=500, min_text_chars=1, min_avg_chars_per_page=1.0)
    assert result.document is not None, f"benchmark case {name!r} failed to parse"
    return BenchmarkCase(name=name, category=category, parsed=result.document, gold_boundaries=gold)


def _docx_case(
    name: str, category: str, items: list[tuple[str, str, bool]], include_table: bool = False
) -> BenchmarkCase:
    """`items`: (style, text, is_boundary). Heading-styled items are never
    boundaries themselves in the gold set (they become `section_heading`
    metadata, not their own clause — matching `segment_document`'s design)."""
    docx_items = [(style, text) for style, text, _ in items]
    gold = frozenset(
        i for i, (style, _, is_boundary) in enumerate(items) if is_boundary and style != "Heading 1"
    )
    data = build_docx(items=docx_items, include_table=include_table)
    result = parse_docx(data, max_items=5000, min_text_chars=1)
    assert result.document is not None, f"benchmark case {name!r} failed to parse"
    return BenchmarkCase(name=name, category=category, parsed=result.document, gold_boundaries=gold)


def build_benchmark() -> list[BenchmarkCase]:
    cases: list[BenchmarkCase] = []

    # 1. Clean numbered PDF -----------------------------------------------
    cases.append(
        _pdf_case(
            "clean_numbered_pdf",
            "clean_pdf_numbered",
            [
                ("1. Prepayment. Borrower may prepay subject to a 2% fee.", True),
                ("2. Default. A missed payment constitutes default.", True),
                ("3. Termination. Either party may terminate with 30 days notice.", True),
            ],
        )
    )

    # 2. Nested numbering ----------------------------------------------------
    cases.append(
        _pdf_case(
            "nested_numbering_pdf",
            "numbered_nested",
            [
                ("1. Repayment. This section governs repayment.", True),
                ("1.1 Borrower shall repay in 12 equal instalments.", True),
                ("1.2 Each instalment is due monthly.", True),
                ("2. Default. This section governs default.", True),
            ],
        )
    )

    # 3. Lettered subclauses ---------------------------------------------------
    cases.append(
        _pdf_case(
            "lettered_subclauses_pdf",
            "lettered",
            [
                ("5. Events of Default include the following:", True),
                ("(a) a missed payment within 10 days of the due date;", True),
                ("(b) breach of a material term of this agreement;", True),
                ("(c) insolvency of the Borrower.", True),
            ],
        )
    )

    # 4. Unstructured prose -------------------------------------------------------
    cases.append(
        _pdf_case(
            "unstructured_prose_pdf",
            "unstructured_prose",
            [
                ("This agreement is entered into between the lender and the borrower.", True),
                ("The borrower agrees to repay the amount borrowed over time.", False),
                ("Both parties agree to act in good faith throughout the term.", False),
            ],
        )
    )

    # 5. Mixed formatting -----------------------------------------------------------
    cases.append(
        _pdf_case(
            "mixed_formatting_pdf",
            "mixed_formatting",
            [
                ("LOAN AGREEMENT", True),
                ("1. Prepayment. Subject to conditions below:", True),
                ("(a) a 2% fee applies if repaid within 12 months;", True),
                ("(b) no fee applies thereafter.", True),
                ("2. Default. Any of the following is a default:", True),
                ("(i) a missed payment;", True),
                ("(ii) a breach of a material covenant.", True),
            ],
        )
    )

    # 6. DOCX headings without numbering ----------------------------------------------
    cases.append(
        _docx_case(
            "docx_headings_no_numbering",
            "docx_headings",
            [
                ("Heading 1", "Definitions", False),
                ("Normal", "In this agreement, Borrower means the party receiving the loan.", True),
                ("Heading 1", "Repayment", False),
                ("Normal", "The Borrower shall repay the loan per the schedule.", True),
            ],
        )
    )

    # 7. DOCX with table -------------------------------------------------------------
    cases.append(
        _docx_case(
            "docx_with_table",
            "docx_table",
            [
                ("Heading 1", "Fee Schedule", False),
                ("Normal", "The following fees apply under this agreement:", True),
            ],
            include_table=True,
        )
    )

    # 8. Cross-referencing clauses (numbered clause referencing another) -----------------
    cases.append(
        _pdf_case(
            "cross_referencing_clauses_pdf",
            "cross_reference",
            [
                ("1. Default. A default under this agreement has the meaning given in Section 1.1.", True),
                ("1.1 Default means a missed payment as described in Clause 1.", True),
                ("2. Consequence. Upon a default described in Section 1, acceleration applies.", True),
            ],
        )
    )

    # 9. Multi-page clause (continuation across a page break) ----------------------------
    continuation = [
        (f"This is synthetic filler sentence number {i} describing repayment obligations.", False)
        for i in range(40)
    ]
    cases.append(
        _pdf_case(
            "multi_page_clause_pdf",
            "multi_page_clause",
            [
                ("1. Repayment. This section describes repayment in detail below.", True),
                *continuation,
                ("2. Default. A short default clause.", True),
            ],
        )
    )

    # 10. Difficult layout: many short fragments with inconsistent structure -------------
    cases.append(
        _pdf_case(
            "difficult_layout_pdf",
            "difficult_layout",
            [
                (Paragraph("odd fragment", bold=True), True),
                ("5. skip ahead", True),
                ("(z) an unusual lettered marker", True),
                ("Section 99.99 an unusual section reference", True),
                ("just some trailing prose with no structure at all", True),
            ],
        )
    )

    return cases
