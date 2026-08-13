"""Content-type gate on `POST /v1/documents` — Phase 10 security audit,
pip-audit finding PYSEC-2026-249 (starlette's `request.form()` silently
ignores its own `max_fields`/`max_part_size` limits for
`application/x-www-form-urlencoded` bodies, only enforcing them for
`multipart/form-data`). See `app/main.py::reject_non_multipart_upload_body`
for the full rationale — this is the regression test proving the
mitigation actually rejects the vulnerable content type before it would
ever reach that parsing path, while leaving the legitimate multipart
upload flow untouched.
"""

from __future__ import annotations

from tests.fixtures.synthetic_documents import build_pdf


class TestUploadContentTypeGate:
    def test_legitimate_multipart_upload_still_succeeds(self, make_client):
        client = make_client()
        response = client.post(
            "/v1/documents", files={"file": ("contract.pdf", build_pdf(), "application/pdf")}
        )
        assert response.status_code == 201

    def test_urlencoded_body_is_rejected_before_form_parsing(self, make_client):
        client = make_client()
        response = client.post(
            "/v1/documents",
            content=b"a=" + b"1" * 1000,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        assert response.status_code == 415
        body = response.json()
        assert body["error"]["code"] == "unsupported_file_type"
        assert "request_id" in body["error"]

    def test_missing_content_type_is_rejected(self, make_client):
        client = make_client()
        response = client.post("/v1/documents", content=b"raw bytes with no content-type")
        assert response.status_code == 415

    def test_gate_does_not_apply_to_read_endpoints(self, make_client, db_session):
        """The gate is scoped to the upload route only -- a GET with no
        body on an unrelated path must never be affected."""
        from tests.conftest import make_document

        client = make_client()
        document = make_document(access_token="g" * 64)
        db_session.add(document)
        db_session.commit()

        response = client.get(
            f"/v1/documents/{document.id}/status",
            headers={"Authorization": f"Bearer {document.access_token}"},
        )
        assert response.status_code == 200
