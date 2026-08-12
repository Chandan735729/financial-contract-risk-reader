"""Synthetic multi-paragraph PDF builders for Phase 3 segmentation tests.

Phase 2's `synthetic_documents.build_pdf()` inserts one page's text as a
*single* string, which PyMuPDF's block detector keeps as one block — fine
for parser smoke tests, but useless for segmentation tests that need
separate paragraph-level blocks. These builders insert each paragraph as
its own `insert_text()` call at a distinct y-position, which PyMuPDF
reliably splits into separate text blocks (verified empirically).

`synthetic_documents.build_docx()` already supports arbitrary
(style, text) items and is reused as-is for DOCX segmentation fixtures —
no DOCX equivalent needed here.

All content is synthetic, clearly fictional contract-style text.
"""

from __future__ import annotations

from dataclasses import dataclass

import pymupdf

_PAGE_HEIGHT = 792.0
_MARGIN_TOP = 72.0
_MARGIN_BOTTOM = 72.0
_LINE_HEIGHT = 16.0
_FONTSIZE = 11.0
_CHARS_PER_LINE = 90  # rough wrap width for multi-line paragraph estimation


@dataclass(frozen=True)
class Paragraph:
    text: str
    bold: bool = False


def _wrapped_line_count(text: str) -> int:
    return max(1, -(-len(text) // _CHARS_PER_LINE))  # ceil division


def build_pdf_paragraphs(
    paragraphs: list[Paragraph | str],
    *,
    header: str | None = None,
    footer: str | None = None,
) -> bytes:
    """Builds a PDF where each paragraph is its own PyMuPDF text block,
    auto-wrapping to a new page when it would overflow the page height.
    `header`/`footer`, if given, are inserted on every page — used for the
    repeated-header/footer suppression test cases.
    """
    items = [p if isinstance(p, Paragraph) else Paragraph(text=p) for p in paragraphs]

    doc = pymupdf.open()
    page = doc.new_page()
    y = _MARGIN_TOP
    if header:
        page.insert_text((72, y), header, fontsize=_FONTSIZE)
        y += _LINE_HEIGHT * 2

    for item in items:
        needed = _wrapped_line_count(item.text) * _LINE_HEIGHT
        if y + needed > _PAGE_HEIGHT - _MARGIN_BOTTOM:
            if footer:
                page.insert_text((72, _PAGE_HEIGHT - _MARGIN_BOTTOM + 20), footer, fontsize=_FONTSIZE)
            page = doc.new_page()
            y = _MARGIN_TOP
            if header:
                page.insert_text((72, y), header, fontsize=_FONTSIZE)
                y += _LINE_HEIGHT * 2

        fontname = "Helvetica-Bold" if item.bold else "Helvetica"
        page.insert_text((72, y), item.text, fontsize=_FONTSIZE, fontname=fontname)
        y += needed + (_LINE_HEIGHT * 0.5)

    if footer:
        page.insert_text((72, _PAGE_HEIGHT - _MARGIN_BOTTOM + 20), footer, fontsize=_FONTSIZE)

    data = doc.tobytes()
    doc.close()
    return data
