"""Secure file storage tests — Phase 2 spec SS3 (secure file handling)."""

from __future__ import annotations

import uuid

import pytest

from app.services.storage import delete_document_file, sanitize_original_filename, save_document_file


class TestSanitizeOriginalFilename:
    def test_plain_filename_unchanged(self):
        assert sanitize_original_filename("contract.pdf") == "contract.pdf"

    def test_none_input_returns_none(self):
        assert sanitize_original_filename(None) is None

    def test_empty_string_returns_none(self):
        assert sanitize_original_filename("") is None

    def test_unix_path_traversal_stripped_to_basename(self):
        result = sanitize_original_filename("../../etc/passwd")
        assert result == "passwd"
        assert "/" not in result
        assert ".." not in result

    def test_windows_absolute_path_stripped_to_basename(self):
        result = sanitize_original_filename("C:\\Windows\\System32\\evil.pdf")
        assert result == "evil.pdf"
        assert "\\" not in result
        assert ":" not in result

    def test_unix_absolute_path_stripped_to_basename(self):
        result = sanitize_original_filename("/etc/passwd")
        assert result == "passwd"

    def test_null_byte_stripped(self):
        result = sanitize_original_filename("contract.pdf\x00.exe")
        assert result is not None
        assert "\x00" not in result

    def test_shell_metacharacters_are_not_used_as_a_path_but_are_preserved_as_text(self):
        # Shell metacharacters are never passed to a shell anywhere in this
        # codebase (no subprocess call involves a filename) — sanitization
        # here exists to keep stored *metadata* safe (control chars, path
        # separators), not to shell-escape a string that's never executed.
        result = sanitize_original_filename("contract; rm -rf ~.pdf")
        assert result is not None
        assert "/" not in result

    def test_only_whitespace_after_cleaning_returns_none(self):
        assert sanitize_original_filename("   ") is None

    def test_overlong_filename_truncated(self):
        result = sanitize_original_filename("a" * 500 + ".pdf", max_length=255)
        assert result is not None
        assert len(result) == 255


class TestSaveAndDeleteDocumentFile:
    def test_save_writes_file_with_server_generated_name(self, tmp_path):
        document_id = uuid.uuid4()
        stored_name = save_document_file(str(tmp_path), document_id, "pdf", b"%PDF-1.4 synthetic content")

        assert stored_name == f"{document_id}.pdf"
        assert (tmp_path / stored_name).exists()
        assert (tmp_path / stored_name).read_bytes() == b"%PDF-1.4 synthetic content"

    def test_save_ignores_client_filename_entirely(self, tmp_path):
        # save_document_file's signature has no filename parameter at all —
        # the on-disk name is derived only from the server-generated UUID.
        import inspect

        from app.services.storage import save_document_file as fn

        assert "filename" not in inspect.signature(fn).parameters

    def test_save_creates_upload_dir_if_missing(self, tmp_path):
        nested = tmp_path / "does" / "not" / "exist" / "yet"
        document_id = uuid.uuid4()
        save_document_file(str(nested), document_id, "docx", b"PK\x03\x04 synthetic")
        assert (nested / f"{document_id}.docx").exists()

    def test_no_leftover_temp_file_after_successful_save(self, tmp_path):
        document_id = uuid.uuid4()
        save_document_file(str(tmp_path), document_id, "pdf", b"synthetic")
        remaining = list(tmp_path.iterdir())
        assert remaining == [tmp_path / f"{document_id}.pdf"]

    def test_delete_removes_file(self, tmp_path):
        document_id = uuid.uuid4()
        stored_name = save_document_file(str(tmp_path), document_id, "pdf", b"synthetic")
        delete_document_file(str(tmp_path), stored_name)
        assert not (tmp_path / stored_name).exists()

    def test_delete_is_idempotent_on_missing_file(self, tmp_path):
        # Cleanup must never raise even if the file was already removed —
        # both the failed-processing and retention-deletion call sites rely
        # on this (Phase 2 spec SS3, SS14).
        delete_document_file(str(tmp_path), "does-not-exist.pdf")

    def test_delete_refuses_to_escape_upload_dir(self, tmp_path):
        outside_dir = tmp_path.parent / f"outside-{uuid.uuid4().hex}"
        outside_dir.mkdir()
        victim = outside_dir / "victim.pdf"
        victim.write_bytes(b"do not delete me")

        upload_dir = tmp_path / "uploads"
        upload_dir.mkdir()
        # Even if a caller somehow passed a traversal-shaped storage_path
        # (never possible via save_document_file's own return value, but
        # defense in depth), delete must not follow it outside upload_dir.
        delete_document_file(str(upload_dir), f"../{outside_dir.name}/victim.pdf")

        assert victim.exists()

    @pytest.mark.parametrize("source_type", ["pdf", "docx"])
    def test_save_uses_correct_extension_for_source_type(self, tmp_path, source_type):
        document_id = uuid.uuid4()
        stored_name = save_document_file(str(tmp_path), document_id, source_type, b"synthetic")
        assert stored_name.endswith(f".{source_type}")
