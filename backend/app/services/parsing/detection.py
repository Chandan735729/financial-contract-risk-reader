"""Actual-content file-type detection — Security_and_Privacy_v2.md SS2:
"validate actual file structure (not extension)".

Never trusts the client-supplied filename or `Content-Type` header. PDF and
DOCX are told apart purely from their byte signatures, since a DOCX (and
XLSX/PPTX) is itself an OOXML ZIP archive that begins with the generic ZIP
local-file-header magic — so telling it apart from an arbitrary ZIP requires
looking inside for the OOXML content-types manifest, not just the first four
bytes.
"""

from __future__ import annotations

import zipfile
from io import BytesIO
from typing import Literal

DetectedKind = Literal["pdf", "docx", "unknown"]

_PDF_MAGIC = b"%PDF-"
_ZIP_MAGIC = b"PK\x03\x04"
_ZIP_EMPTY_MAGIC = b"PK\x05\x06"  # empty zip archive — still a valid signature
_DOCX_CONTENT_TYPES_ENTRY = "[Content_Types].xml"
_DOCX_MAIN_DOCUMENT_ENTRY = "word/document.xml"


def detect_file_kind(data: bytes) -> DetectedKind:
    """Sniff the real file type from its bytes. Returns "unknown" for
    anything that isn't a structurally plausible PDF or DOCX — the caller
    maps "unknown" to `ErrorCode.UNSUPPORTED_FILE_TYPE` or
    `ErrorCode.CORRUPTED_FILE` depending on context.
    """
    if data.startswith(_PDF_MAGIC):
        return "pdf"

    if data.startswith(_ZIP_MAGIC) or data.startswith(_ZIP_EMPTY_MAGIC):
        if _is_ooxml_wordprocessing_package(data):
            return "docx"
        return "unknown"

    return "unknown"


def _is_ooxml_wordprocessing_package(data: bytes) -> bool:
    try:
        with zipfile.ZipFile(BytesIO(data)) as archive:
            names = set(archive.namelist())
    except (zipfile.BadZipFile, OSError):
        return False

    return _DOCX_CONTENT_TYPES_ENTRY in names and _DOCX_MAIN_DOCUMENT_ENTRY in names
