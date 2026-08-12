"""Text-preservation invariant tests — Phase 3 spec SS10.

Proves `validate_invariants` both passes clean segmentation output *and*
actually catches each kind of violation when hand-fed a broken result —
otherwise a validator that always returns `[]` would pass silently.
"""

from __future__ import annotations

from typing import Any

from app.services.parsing.docx_parser import parse_docx
from app.services.parsing.models import DocumentTextBlock, ParsedDocument
from app.services.parsing.pdf_parser import parse_pdf
from app.services.segmentation_models import SegmentationDiagnostics, SegmentationResult, SegmentedClause
from app.services.segmentation_service import segment_document, validate_invariants
from tests.fixtures.segmentation_documents import build_pdf_paragraphs
from tests.fixtures.synthetic_documents import build_docx


def _clean_clause(**overrides: Any) -> SegmentedClause:
    defaults: dict[str, Any] = {
        "clause_index": 0,
        "raw_text": "1. Some clause text.",
        "section_heading": None,
        "page_number": 1,
        "start_char": 0,
        "end_char": 20,
        "segmentation_confidence": 0.9,
        "low_confidence_flag": False,
        "boundary_signal": "top_numeric",
        "block_count": 1,
        "start_block_order": 0,
    }
    defaults.update(overrides)
    return SegmentedClause(**defaults)


def _diagnostics(**overrides: Any) -> SegmentationDiagnostics:
    defaults: dict[str, Any] = {
        "total_blocks": 1,
        "suppressed_block_count": 0,
        "heading_block_count": 0,
        "total_chars": 20,
        "suppressed_chars": 0,
        "heading_metadata_chars": 0,
        "covered_chars": 20,
    }
    defaults.update(overrides)
    return SegmentationDiagnostics(**defaults)


def _block(**overrides: Any) -> DocumentTextBlock:
    defaults: dict[str, Any] = {
        "text": "1. Some clause text.",
        "order": 0,
        "source_type": "pdf",
        "page_number": 1,
        "start_char": 0,
        "end_char": 20,
    }
    defaults.update(overrides)
    return DocumentTextBlock(**defaults)


class TestRealSegmentationPasses:
    def test_clean_pdf_document_has_no_violations(self):
        data = build_pdf_paragraphs(
            [
                "1. Prepayment. Borrower may prepay subject to a 2% fee.",
                "2. Default. A missed payment constitutes default.",
            ]
        )
        parsed = parse_pdf(data, max_pages=200, min_text_chars=1, min_avg_chars_per_page=1.0).document
        assert parsed is not None
        result = segment_document(parsed)
        assert validate_invariants(parsed, result) == []

    def test_clean_docx_document_has_no_violations(self):
        data = build_docx()
        parsed = parse_docx(data, max_items=5000, min_text_chars=1).document
        assert parsed is not None
        result = segment_document(parsed)
        assert validate_invariants(parsed, result) == []


class TestViolationsAreDetected:
    def test_non_sequential_clause_index_is_caught(self):
        parsed = ParsedDocument(source_type="pdf", blocks=(_block(),))
        clauses = (_clean_clause(clause_index=0), _clean_clause(clause_index=2, start_block_order=1))
        result = SegmentationResult(clauses=clauses, diagnostics=_diagnostics())
        violations = validate_invariants(parsed, result)
        assert any("sequential" in v for v in violations)

    def test_out_of_order_reading_order_is_caught(self):
        parsed = ParsedDocument(source_type="pdf", blocks=(_block(),))
        clauses = (
            _clean_clause(clause_index=0, start_block_order=5),
            _clean_clause(clause_index=1, start_block_order=2),
        )
        result = SegmentationResult(clauses=clauses, diagnostics=_diagnostics())
        violations = validate_invariants(parsed, result)
        assert any("reading order" in v for v in violations)

    def test_empty_raw_text_is_caught(self):
        parsed = ParsedDocument(source_type="pdf", blocks=(_block(),))
        clauses = (_clean_clause(raw_text="   "),)
        result = SegmentationResult(clauses=clauses, diagnostics=_diagnostics())
        violations = validate_invariants(parsed, result)
        assert any("empty raw_text" in v for v in violations)

    def test_char_accounting_mismatch_is_caught(self):
        parsed = ParsedDocument(source_type="pdf", blocks=(_block(),))
        bad_diagnostics = _diagnostics(
            total_chars=100, covered_chars=20, suppressed_chars=0, heading_metadata_chars=0
        )
        result = SegmentationResult(clauses=(_clean_clause(),), diagnostics=bad_diagnostics)
        violations = validate_invariants(parsed, result)
        assert any("char accounting mismatch" in v for v in violations)

    def test_invalid_page_number_is_caught(self):
        parsed = ParsedDocument(source_type="pdf", blocks=(_block(page_number=1),))
        clauses = (_clean_clause(page_number=99),)
        result = SegmentationResult(clauses=clauses, diagnostics=_diagnostics())
        violations = validate_invariants(parsed, result)
        assert any("page_number" in v for v in violations)

    def test_untraceable_start_char_is_caught(self):
        parsed = ParsedDocument(source_type="pdf", blocks=(_block(start_char=0, end_char=20),))
        clauses = (_clean_clause(start_char=9999, end_char=20),)
        result = SegmentationResult(clauses=clauses, diagnostics=_diagnostics())
        violations = validate_invariants(parsed, result)
        assert any("not traceable to a source block" in v for v in violations)

    def test_start_after_end_is_caught(self):
        parsed = ParsedDocument(source_type="pdf", blocks=(_block(start_char=0, end_char=20),))
        clauses = (_clean_clause(start_char=20, end_char=0),)
        result = SegmentationResult(clauses=clauses, diagnostics=_diagnostics())
        violations = validate_invariants(parsed, result)
        assert any("start_char > end_char" in v for v in violations)
