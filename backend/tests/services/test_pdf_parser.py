"""PDF parser tests — Technical_Architecture_v2.md SS3, Phase 2 spec SS4."""

from __future__ import annotations

from app.models.enums import ErrorCode
from app.services.parsing.models import ParsedDocument, ParseResult, ParseStatus
from app.services.parsing.pdf_parser import parse_pdf
from tests.fixtures.synthetic_documents import (
    build_corrupted_pdf,
    build_empty_pdf,
    build_password_protected_pdf,
    build_pdf,
    build_scanned_pdf,
)


def _parse(
    data: bytes, *, max_pages: int = 200, min_text_chars: int = 50, min_avg_chars_per_page: float = 5.0
) -> ParseResult:
    return parse_pdf(
        data,
        max_pages=max_pages,
        min_text_chars=min_text_chars,
        min_avg_chars_per_page=min_avg_chars_per_page,
    )


def _require_document(result: ParseResult) -> ParsedDocument:
    assert result.document is not None
    return result.document


def test_normal_text_pdf_parses_successfully():
    result = _parse(build_pdf())
    assert result.status == ParseStatus.SUCCESS
    assert result.is_success
    assert result.error_code is None
    document = _require_document(result)
    assert document.page_count == len(document.blocks)  # one page per synthetic clause block
    assert document.total_text_length > 0


def test_page_and_text_ordering_preserved():
    pages = ["Page one synthetic clause about a 2% fee.", "Page two synthetic clause about default."]
    document = _require_document(_parse(build_pdf(pages)))
    blocks = document.blocks
    assert [b.order for b in blocks] == list(range(len(blocks)))
    assert [b.page_number for b in blocks] == [1, 2]
    assert blocks[0].text.strip().startswith("Page one")
    assert blocks[1].text.strip().startswith("Page two")


def test_bounding_box_preserved():
    document = _require_document(_parse(build_pdf()))
    for block in document.blocks:
        assert block.bounding_box is not None
        assert block.bounding_box.x1 > block.bounding_box.x0
        assert block.bounding_box.y1 > block.bounding_box.y0


def test_multi_page_document_extracts_all_pages():
    pages = [f"Synthetic clause number {i} about a financial term." for i in range(5)]
    document = _require_document(_parse(build_pdf(pages)))
    assert document.page_count == 5
    assert {b.page_number for b in document.blocks} == {1, 2, 3, 4, 5}


def test_empty_pdf_is_low_text_content():
    result = _parse(build_empty_pdf())
    assert not result.is_success
    assert result.status in (ParseStatus.EMPTY, ParseStatus.LOW_TEXT)
    assert result.error_code == ErrorCode.LOW_TEXT_CONTENT


def test_scanned_image_only_pdf_is_low_text_content():
    result = _parse(build_scanned_pdf())
    assert not result.is_success
    assert result.status == ParseStatus.SCANNED
    assert result.error_code == ErrorCode.LOW_TEXT_CONTENT


def test_near_empty_text_below_average_threshold_is_low_text_content():
    # Many pages, trivial text on only one of them — total might clear the
    # absolute floor but the average must still catch it.
    pages = ["x"] * 10
    result = _parse(build_pdf(pages), min_text_chars=5, min_avg_chars_per_page=5.0)
    assert not result.is_success
    assert result.error_code == ErrorCode.LOW_TEXT_CONTENT


def test_password_protected_pdf_detected_without_bruteforce():
    result = _parse(build_password_protected_pdf())
    assert result.status == ParseStatus.PASSWORD_PROTECTED
    assert result.error_code == ErrorCode.PASSWORD_PROTECTED
    assert result.document is None


def test_corrupted_pdf_returns_corrupted_status_not_exception():
    result = _parse(build_corrupted_pdf())
    assert result.status == ParseStatus.CORRUPTED
    assert result.error_code == ErrorCode.CORRUPTED_FILE
    # No parser internals leak into the safe diagnostic field.
    assert "Traceback" not in (result.detail or "")


def test_too_many_pages_rejected():
    pages = ["Synthetic clause text." for _ in range(3)]
    result = _parse(build_pdf(pages), max_pages=2, min_text_chars=5, min_avg_chars_per_page=1.0)
    assert result.status == ParseStatus.TOO_MANY_PAGES
    assert result.error_code == ErrorCode.FILE_TOO_LARGE


def test_bold_text_flagged_when_present():
    import pymupdf

    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Synthetic bold clause text.", fontsize=11, fontname="Helvetica-Bold")
    data = doc.tobytes()
    doc.close()

    document = _require_document(_parse(data, min_text_chars=1, min_avg_chars_per_page=1.0))
    assert any(b.is_bold for b in document.blocks)
