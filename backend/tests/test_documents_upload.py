"""`POST /v1/documents` integration tests — Phase 2 spec SS1, SS11.

All uploaded content is synthetic, generated at test time (see
tests/fixtures/synthetic_documents.py) — never real financial documents.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.models import db_models
from tests.fixtures.synthetic_documents import (
    build_corrupted_docx,
    build_corrupted_pdf,
    build_docx,
    build_empty_docx,
    build_empty_pdf,
    build_password_protected_pdf,
    build_pdf,
    build_random_binary,
    build_scanned_pdf,
)


def _upload(client, filename: str, data: bytes, content_type: str = "application/octet-stream"):
    return client.post("/v1/documents", files={"file": (filename, data, content_type)})


class TestSuccessfulUpload:
    def test_valid_pdf_upload_returns_201_with_document_id_and_token(self, make_client):
        client = make_client()
        response = _upload(client, "contract.pdf", build_pdf(), "application/pdf")

        assert response.status_code == 201
        body = response.json()
        assert set(body.keys()) == {"document_id", "access_token"}
        uuid.UUID(body["document_id"])  # does not raise
        assert len(body["access_token"]) == 64

    def test_valid_docx_upload_returns_201(self, make_client):
        client = make_client()
        response = _upload(
            client,
            "contract.docx",
            build_docx(),
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
        assert response.status_code == 201

    def test_successful_upload_creates_document_and_processing_job(self, make_client, db_session):
        client = make_client()
        # Built once and reused for both the upload and the size assertion —
        # PyMuPDF embeds a creation timestamp, so two separate build_pdf()
        # calls can differ by a byte if they straddle a second boundary.
        pdf_bytes = build_pdf()
        body = _upload(client, "contract.pdf", pdf_bytes, "application/pdf").json()
        document_id = uuid.UUID(body["document_id"])

        document = db_session.get(db_models.Document, document_id)
        assert document is not None
        assert document.access_token == body["access_token"]
        assert document.file_format == "pdf"
        assert document.file_size_bytes == len(pdf_bytes)
        assert document.page_count == 6
        assert document.document_type == db_models.DocumentType.UNKNOWN
        assert document.original_filename == "contract.pdf"

        # Phase 8: upload schedules the rest of the pipeline as a
        # BackgroundTasks job, which `TestClient` runs synchronously before
        # returning control here — so by this point the job has already
        # run segmentation through generation and reached COMPLETED (this
        # fixture's single clause has no rule/entity/retrieval signal, so it
        # abstains to UNKNOWN — see the dedicated pipeline tests for
        # HIGH/MEDIUM/LOW/UNKNOWN coverage).
        job = db_session.scalars(
            select(db_models.ProcessingJob).where(db_models.ProcessingJob.document_id == document_id)
        ).one()
        assert job.stage == db_models.ProcessingStage.COMPLETED
        assert job.error_code is None

    def test_wrong_extension_is_ignored_content_still_sniffed(self, make_client):
        # Real PDF bytes under a misleading .txt filename must still succeed
        # — extension is never trusted (Phase 2 spec SS2).
        client = make_client()
        response = _upload(client, "notes.txt", build_pdf(), "text/plain")
        assert response.status_code == 201

    def test_incorrect_mime_type_is_ignored_content_still_sniffed(self, make_client):
        client = make_client()
        response = _upload(client, "contract.pdf", build_pdf(), "image/png")
        assert response.status_code == 201


class TestValidationFailures:
    def test_random_binary_file_rejected_as_unsupported_type(self, make_client):
        client = make_client()
        response = _upload(client, "file.bin", build_random_binary())
        assert response.status_code == 415
        assert response.json()["error"]["code"] == "unsupported_file_type"

    def test_corrupted_pdf_rejected(self, make_client):
        client = make_client()
        response = _upload(client, "contract.pdf", build_corrupted_pdf(), "application/pdf")
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "corrupted_file"

    def test_corrupted_docx_rejected(self, make_client):
        client = make_client()
        response = _upload(
            client,
            "contract.docx",
            build_corrupted_docx(),
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "corrupted_file"

    def test_empty_pdf_rejected_as_low_text_content(self, make_client):
        client = make_client()
        response = _upload(client, "contract.pdf", build_empty_pdf(), "application/pdf")
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "low_text_content"

    def test_empty_docx_rejected_as_low_text_content(self, make_client):
        client = make_client()
        response = _upload(
            client,
            "contract.docx",
            build_empty_docx(),
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "low_text_content"

    def test_scanned_pdf_rejected_as_low_text_content(self, make_client):
        client = make_client()
        response = _upload(client, "scan.pdf", build_scanned_pdf(), "application/pdf")
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "low_text_content"

    def test_password_protected_pdf_rejected(self, make_client):
        client = make_client()
        response = _upload(client, "contract.pdf", build_password_protected_pdf(), "application/pdf")
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "password_protected"

    def test_oversized_file_rejected(self, make_client):
        client = make_client(max_upload_size_bytes=100)
        response = _upload(client, "contract.pdf", build_pdf(), "application/pdf")
        assert response.status_code == 413
        assert response.json()["error"]["code"] == "file_too_large"

    def test_too_many_pages_rejected(self, make_client):
        client = make_client(max_pdf_pages=2)
        response = _upload(client, "contract.pdf", build_pdf(), "application/pdf")  # 6 synthetic pages
        assert response.status_code == 413
        assert response.json()["error"]["code"] == "file_too_large"

    def test_error_response_never_includes_document_id(self, make_client):
        client = make_client()
        response = _upload(client, "file.bin", build_random_binary())
        assert "document_id" not in response.json()
        assert "document_id" not in response.json().get("error", {})


class TestSecurity:
    def test_path_traversal_filename_does_not_escape_upload_dir(self, make_client, db_session):
        client = make_client()
        response = _upload(client, "../../etc/passwd.pdf", build_pdf(), "application/pdf")
        assert response.status_code == 201

        document_id = uuid.UUID(response.json()["document_id"])
        document = db_session.get(db_models.Document, document_id)
        assert document.original_filename == "passwd.pdf"
        assert ".." not in document.storage_path
        assert "/" not in document.storage_path

    def test_windows_absolute_path_filename_sanitized(self, make_client, db_session):
        client = make_client()
        response = _upload(client, "C:\\Windows\\System32\\evil.pdf", build_pdf(), "application/pdf")
        assert response.status_code == 201

        document_id = uuid.UUID(response.json()["document_id"])
        document = db_session.get(db_models.Document, document_id)
        assert document.original_filename == "evil.pdf"

    def test_shell_metacharacter_filename_does_not_crash_upload(self, make_client):
        client = make_client()
        response = _upload(client, "contract; rm -rf ~.pdf", build_pdf(), "application/pdf")
        assert response.status_code == 201

    def test_null_byte_filename_if_runtime_permits(self, make_client):
        client = make_client()
        try:
            response = _upload(client, "contract.pdf\x00.exe", build_pdf(), "application/pdf")
        except (ValueError, UnicodeError):
            pytest.skip("test runtime rejects a null byte in a multipart filename before it reaches the app")
            return
        # Whether the HTTP layer accepts or rejects the header, the app must
        # never crash (500) on it.
        assert response.status_code != 500

    def test_unsupported_type_never_reaches_parser(self, make_client, monkeypatch):
        import app.api.documents as documents_module

        def _fail_if_called(*_args, **_kwargs):
            raise AssertionError("parser must not be called for an unsupported file type")

        monkeypatch.setattr(documents_module, "parse_pdf", _fail_if_called)
        monkeypatch.setattr(documents_module, "parse_docx", _fail_if_called)

        client = make_client()
        response = _upload(client, "file.bin", build_random_binary())
        assert response.status_code == 415

    def test_failed_upload_leaves_no_file_on_disk(self, make_client, tmp_path):
        client = make_client()
        _upload(client, "contract.pdf", build_corrupted_pdf(), "application/pdf")

        uploads_dir = tmp_path / "uploads"
        remaining = list(uploads_dir.iterdir()) if uploads_dir.exists() else []
        assert remaining == []

    def test_failed_upload_creates_no_document_row(self, make_client, db_session):
        client = make_client()
        _upload(client, "contract.pdf", build_corrupted_pdf(), "application/pdf")

        count = db_session.scalar(select(db_models.Document).limit(1))
        assert count is None

    def test_duplicate_access_token_cleans_up_orphan_file(
        self, make_client, db_session, tmp_path, monkeypatch
    ):
        import app.api.documents as documents_module

        monkeypatch.setattr(documents_module.secrets, "token_urlsafe", lambda n: "fixed-collision-token")

        client = make_client()
        first = _upload(client, "contract.pdf", build_pdf(), "application/pdf")
        assert first.status_code == 201

        second = _upload(client, "contract2.pdf", build_pdf(), "application/pdf")
        assert second.status_code == 500
        assert second.json()["error"]["code"] == "internal_error"

        # Only the first upload's file remains — the second's storage write
        # must have been cleaned up after the DB unique-constraint failure.
        uploads_dir = tmp_path / "uploads"
        assert len(list(uploads_dir.iterdir())) == 1

        documents = db_session.scalars(select(db_models.Document)).all()
        assert len(documents) == 1

    def test_response_never_contains_a_filesystem_path(self, make_client, tmp_path):
        client = make_client()
        response = _upload(client, "contract.pdf", build_pdf(), "application/pdf")
        text = response.text
        assert str(tmp_path) not in text
        assert "uploads" not in text
        assert "\\" not in text  # no Windows path separators anywhere in the body

    def test_access_token_and_raw_content_never_logged(self, make_client, caplog):
        import logging

        client = make_client()
        with caplog.at_level(logging.DEBUG):
            response = _upload(client, "contract.pdf", build_pdf(), "application/pdf")

        access_token = response.json()["access_token"]
        log_text = "\n".join(record.getMessage() for record in caplog.records)
        log_text += "\n".join(str(getattr(record, "fields", "")) for record in caplog.records)

        assert access_token not in log_text
        assert "prepayment penalty" not in log_text.lower()
        assert "$1,000" not in log_text

    def test_backend_secrets_never_appear_in_response(self, make_client):
        client = make_client()
        response = _upload(client, "contract.pdf", build_pdf(), "application/pdf")
        text = response.text.lower()
        for forbidden in ("anthropic", "database_url", "secret", "traceback"):
            assert forbidden not in text
