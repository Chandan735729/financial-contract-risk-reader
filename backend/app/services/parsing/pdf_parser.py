"""PDF parsing — Technical_Architecture_v2.md SS3 (PyMuPDF).

Parses from an in-memory byte string only (never writes the untrusted
upload to disk before/during parsing — see app/services/storage.py for the
separate, post-validation permanent-storage write).

Never attempts to guess or brute-force a PDF password: exactly one
empty-string authentication attempt distinguishes "owner-password-only, but
content readable" PDFs (common from some export tools) from genuinely
user-password-locked ones (Security_and_Privacy_v2.md SS2; Phase 2 spec
SS7 "do not brute force passwords").
"""

from __future__ import annotations

import pymupdf

from app.services.parsing.models import (
    BoundingBox,
    DocumentTextBlock,
    ParsedDocument,
    ParseResult,
    ParseStatus,
)

# PyMuPDF text-span "flags" bitfield (get_text("dict")): bit 4 (value 16) is
# the bold flag. See PyMuPDF docs on `span["flags"]`.
_SPAN_FLAG_BOLD = 1 << 4


def parse_pdf(
    data: bytes, *, max_pages: int, min_text_chars: int, min_avg_chars_per_page: float
) -> ParseResult:
    try:
        doc = pymupdf.open(stream=data, filetype="pdf")
    except Exception:
        # Only the exception *type* would be useful here, and even that is
        # left to the caller's logging — this function returns a typed
        # result, never raises, so parser internals never reach the caller.
        return ParseResult(status=ParseStatus.CORRUPTED, detail="failed to open as PDF")

    try:
        return _parse_opened_pdf(
            doc,
            max_pages=max_pages,
            min_text_chars=min_text_chars,
            min_avg_chars_per_page=min_avg_chars_per_page,
        )
    finally:
        doc.close()


def _parse_opened_pdf(
    doc: pymupdf.Document,
    *,
    max_pages: int,
    min_text_chars: int,
    min_avg_chars_per_page: float,
) -> ParseResult:
    # Exactly one attempt with an empty password — see module docstring. A
    # non-zero return means the empty password worked (content is actually
    # readable); zero means it's genuinely locked. `and` short-circuits so
    # authenticate() is only ever called when a password is actually needed.
    if doc.needs_pass and not doc.authenticate(""):
        return ParseResult(status=ParseStatus.PASSWORD_PROTECTED)

    page_count = doc.page_count
    if page_count == 0:
        return ParseResult(status=ParseStatus.EMPTY, detail="0 pages")

    if page_count > max_pages:
        return ParseResult(
            status=ParseStatus.TOO_MANY_PAGES, detail=f"{page_count} pages exceeds max_pages={max_pages}"
        )

    blocks: list[DocumentTextBlock] = []
    order = 0
    char_offset = 0
    has_any_image = False

    for page_index in range(page_count):
        page = doc[page_index]
        page_dict = page.get_text("dict")
        if page.get_images(full=True):
            has_any_image = True

        for raw_block in page_dict.get("blocks", []):
            if raw_block.get("type") != 0:  # 0 == text block; 1 == image block
                continue
            spans = [span for line in raw_block.get("lines", []) for span in line.get("spans", [])]
            block_text = "".join(span.get("text", "") for span in spans)
            if not block_text.strip():
                continue

            bbox_coords = raw_block.get("bbox")
            bounding_box = BoundingBox(*bbox_coords) if bbox_coords else None
            is_bold = any(span.get("flags", 0) & _SPAN_FLAG_BOLD for span in spans)

            start = char_offset
            char_offset += len(block_text)
            blocks.append(
                DocumentTextBlock(
                    text=block_text,
                    order=order,
                    source_type="pdf",
                    page_number=page_index + 1,
                    start_char=start,
                    end_char=char_offset,
                    bounding_box=bounding_box,
                    is_bold=is_bold,
                )
            )
            order += 1

    total_chars = sum(len(b.text) for b in blocks)
    avg_chars_per_page = total_chars / page_count if page_count else 0.0

    if total_chars < min_text_chars:
        status = ParseStatus.SCANNED if has_any_image else ParseStatus.LOW_TEXT
        return ParseResult(
            status=status,
            detail=f"{page_count} pages, {total_chars} extracted chars",
        )

    if avg_chars_per_page < min_avg_chars_per_page:
        return ParseResult(
            status=ParseStatus.SCANNED,
            detail=f"{page_count} pages, avg {avg_chars_per_page:.1f} chars/page",
        )

    return ParseResult(
        status=ParseStatus.SUCCESS,
        document=ParsedDocument(source_type="pdf", blocks=tuple(blocks), page_count=page_count),
        detail=f"{page_count} pages, {total_chars} extracted chars",
    )
