"""File-type sniffing tests — never trust filename/extension/MIME type."""

from __future__ import annotations

from app.services.parsing.detection import detect_file_kind
from tests.fixtures.synthetic_documents import (
    build_corrupted_docx,
    build_corrupted_pdf,
    build_docx,
    build_pdf,
    build_random_binary,
)


def test_detects_valid_pdf():
    assert detect_file_kind(build_pdf()) == "pdf"


def test_detects_valid_docx():
    assert detect_file_kind(build_docx()) == "docx"


def test_random_binary_is_unknown():
    assert detect_file_kind(build_random_binary()) == "unknown"


def test_empty_bytes_is_unknown():
    assert detect_file_kind(b"") == "unknown"


def test_plain_zip_without_ooxml_markers_is_unknown():
    import zipfile
    from io import BytesIO

    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("readme.txt", "just a plain zip, not a docx")
    assert detect_file_kind(buffer.getvalue()) == "unknown"


def test_corrupted_pdf_still_sniffs_as_pdf():
    # Magic bytes are intact even though the body is garbage — detection is
    # a cheap first gate, not full structural validation (the parser catches
    # the rest).
    assert detect_file_kind(build_corrupted_pdf()) == "pdf"


def test_corrupted_docx_still_sniffs_as_docx():
    assert detect_file_kind(build_corrupted_docx()) == "docx"


def test_truncated_docx_is_unknown():
    # Truncating past the ZIP central directory breaks the zip itself, so
    # this is a different failure mode than build_corrupted_docx() (which
    # keeps the zip valid but garbles one entry's content).
    truncated = build_docx()[:20]
    assert detect_file_kind(truncated) == "unknown"


def test_filename_and_content_type_are_never_consulted():
    # detect_file_kind's signature takes only bytes — there is no
    # filename/content-type parameter to trust in the first place.
    import inspect

    params = inspect.signature(detect_file_kind).parameters
    assert list(params) == ["data"]
