"""Secure storage for uploaded document originals — Security_and_Privacy_v2.md
SS2: "store originals in object storage separate from the database."

MVP storage strategy (local filesystem) is a documented provisional
decision — see docs/PROVISIONAL_DECISIONS.md "Phase 2: uploaded document
storage strategy." The interface here (`save_document_file` /
`delete_document_file`, operating on an opaque `storage_path` string) is
intentionally the same shape a future S3/GCS-backed implementation would
have, so swapping the backend later doesn't ripple into the upload endpoint.

Path-traversal safety: the on-disk filename is always server-generated from
a `uuid.UUID` this service creates itself plus a fixed, internally-chosen
extension — the client-supplied filename and content-type never influence
any filesystem path. `sanitize_original_filename` exists only to make the
*stored metadata* safe (never fed back into a path), not to make a path safe.
"""

from __future__ import annotations

import os
import re
import uuid
from pathlib import Path
from typing import Literal

_EXTENSION_BY_SOURCE_TYPE: dict[str, str] = {"pdf": ".pdf", "docx": ".docx"}

# Strips path separators, drive letters, and control/null characters from a
# client-supplied filename before it's stored as metadata. Never used to
# build a filesystem path (see module docstring) — this only prevents a
# hostile filename from corrupting logs, DB text columns, or a future UI
# that renders it verbatim.
_UNSAFE_FILENAME_CHARS = re.compile(r"[\x00-\x1f\x7f/\\:]")


def sanitize_original_filename(filename: str | None, *, max_length: int = 255) -> str | None:
    if not filename:
        return None
    # Drop any directory components a hostile client embedded (e.g.
    # "../../etc/passwd" or "C:\\Windows\\System32\\evil") — keep only the
    # last path segment's basename, then strip remaining unsafe characters.
    basename = filename.replace("\\", "/").rsplit("/", 1)[-1]
    cleaned = _UNSAFE_FILENAME_CHARS.sub("", basename).strip()
    if not cleaned:
        return None
    return cleaned[:max_length]


def _document_storage_path(
    upload_dir: Path, document_id: uuid.UUID, source_type: Literal["pdf", "docx"]
) -> Path:
    extension = _EXTENSION_BY_SOURCE_TYPE[source_type]
    return upload_dir / f"{document_id}{extension}"


def save_document_file(
    upload_dir: str, document_id: uuid.UUID, source_type: Literal["pdf", "docx"], data: bytes
) -> str:
    """Persist validated file bytes to permanent storage. Returns the
    storage reference to save in `documents.storage_path` — never an
    absolute path suitable for exposing to a client (API_and_Data_Models.md
    never returns this field; see Phase 2 spec SS1 "Do NOT expose filesystem
    paths").

    Writes to a temp file in the same directory and atomically renames it
    into place, so a crash mid-write never leaves a half-written file at the
    final path.
    """
    base_dir = Path(upload_dir).resolve()
    base_dir.mkdir(parents=True, exist_ok=True)
    final_path = _document_storage_path(base_dir, document_id, source_type)
    tmp_path = final_path.with_suffix(final_path.suffix + f".{uuid.uuid4().hex}.tmp")

    try:
        tmp_path.write_bytes(data)
        os.replace(tmp_path, final_path)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise

    return final_path.name


def delete_document_file(upload_dir: str, storage_path: str) -> None:
    """Idempotent cleanup — used both for failed-upload rollback and future
    retention/deletion jobs. Never raises if the file is already gone."""
    base_dir = Path(upload_dir).resolve()
    target = (base_dir / storage_path).resolve()
    # Defense in depth: even though `storage_path` is always a bare
    # server-generated filename (never client input), refuse to delete
    # anything that resolves outside the upload directory.
    if base_dir not in target.parents and target != base_dir:
        return
    target.unlink(missing_ok=True)
