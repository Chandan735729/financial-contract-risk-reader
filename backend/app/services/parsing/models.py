"""Internal parser contract — Technical_Architecture_v2.md SS3 (Parsing Service).

Deliberately not a Pydantic/API model and not a SQLAlchemy model: this is the
in-memory representation the parser hands to the (not-yet-implemented)
Segmentation Service in a later phase. Phase 2 does not persist any of this
to the database — see docs/PROVISIONAL_DECISIONS.md "Phase 2: parsed text is
not persisted."

Frozen dataclasses (not Pydantic) on purpose: this contract never crosses a
process/API boundary, so it doesn't need Pydantic's validation/serialization
machinery — a plain, cheap, internal-only value type is the right altitude.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Literal

from app.models.enums import ErrorCode

SourceType = Literal["pdf", "docx"]


@dataclass(frozen=True, slots=True)
class BoundingBox:
    x0: float
    y0: float
    x1: float
    y1: float


@dataclass(frozen=True, slots=True)
class DocumentTextBlock:
    """One unit of extracted text (a PDF text block or a DOCX paragraph/cell)."""

    text: str
    order: int
    source_type: SourceType
    page_number: int | None = None
    start_char: int | None = None
    end_char: int | None = None
    bounding_box: BoundingBox | None = None
    # e.g. "Heading1", "Normal", "TableCell" — whatever style/heading signal
    # the source format exposes; None where the format has no concept of it.
    style: str | None = None
    is_heading: bool = False
    is_list_item: bool = False
    is_table_cell: bool = False
    is_bold: bool = False


@dataclass(frozen=True, slots=True)
class ParsedDocument:
    """Normalized parser output — the contract Phase 3 segmentation consumes."""

    source_type: SourceType
    blocks: tuple[DocumentTextBlock, ...] = field(default_factory=tuple)
    page_count: int | None = None

    @property
    def total_text_length(self) -> int:
        return sum(len(block.text) for block in self.blocks)


class ParseStatus(str, Enum):
    """Internal parse outcome — finer-grained than the canonical `ErrorCode`
    the API exposes (several of these collapse onto `LOW_TEXT_CONTENT`).
    Not a shared/API enum: never serialized across a process boundary.
    """

    SUCCESS = "success"
    EMPTY = "empty"
    LOW_TEXT = "low_text"
    SCANNED = "scanned"
    PASSWORD_PROTECTED = "password_protected"
    CORRUPTED = "corrupted"
    UNSUPPORTED = "unsupported"
    # No dedicated canonical ErrorCode exists for a page/paragraph-count cap —
    # see docs/PROVISIONAL_DECISIONS.md "Phase 2: too-many-pages error mapping".
    TOO_MANY_PAGES = "too_many_pages"


_FAILURE_STATUS_TO_ERROR_CODE: dict[ParseStatus, ErrorCode] = {
    ParseStatus.EMPTY: ErrorCode.LOW_TEXT_CONTENT,
    ParseStatus.LOW_TEXT: ErrorCode.LOW_TEXT_CONTENT,
    ParseStatus.SCANNED: ErrorCode.LOW_TEXT_CONTENT,
    ParseStatus.PASSWORD_PROTECTED: ErrorCode.PASSWORD_PROTECTED,
    ParseStatus.CORRUPTED: ErrorCode.CORRUPTED_FILE,
    ParseStatus.UNSUPPORTED: ErrorCode.UNSUPPORTED_FILE_TYPE,
    ParseStatus.TOO_MANY_PAGES: ErrorCode.FILE_TOO_LARGE,
}


@dataclass(frozen=True, slots=True)
class ParseResult:
    """Outcome of parsing one uploaded file.

    Exactly one of `document` / `error_code` is set: `status == SUCCESS`
    always carries a `document`; every other status always carries the
    canonical `error_code` it maps to.
    """

    status: ParseStatus
    document: ParsedDocument | None = None
    # Safe, non-sensitive diagnostic only (e.g. "0 pages", "12 pages, avg
    # 3.1 chars/page") — never raw extracted text (Security_and_Privacy_v2.md SS6).
    detail: str | None = None

    @property
    def is_success(self) -> bool:
        return self.status is ParseStatus.SUCCESS

    @property
    def error_code(self) -> ErrorCode | None:
        return _FAILURE_STATUS_TO_ERROR_CODE.get(self.status)
