"""Upload rate limiting — Phase 10 security audit, Security_and_Privacy_v2.md
SS8 ("Upload rate limiting per session/IP"). `ErrorCode.RATE_LIMITED` was
defined (and had a mapped user-facing message on both backend and
frontend) since early phases, but nothing ever actually enforced it until
this phase — this test proves the gap is closed, not just documented.
"""

from __future__ import annotations

from app.models.enums import ErrorCode
from tests.fixtures.synthetic_documents import build_pdf


def _upload(client, pdf_bytes: bytes):
    return client.post("/v1/documents", files={"file": ("contract.pdf", pdf_bytes, "application/pdf")})


class TestUploadRateLimit:
    def test_uploads_within_the_limit_succeed(self, make_client):
        client = make_client(upload_rate_limit_max_requests=2, upload_rate_limit_window_seconds=60.0)
        pdf_bytes = build_pdf()

        first = _upload(client, pdf_bytes)
        second = _upload(client, pdf_bytes)

        assert first.status_code == 201
        assert second.status_code == 201

    def test_upload_beyond_the_limit_is_rejected_with_429_and_the_canonical_error_shape(self, make_client):
        client = make_client(upload_rate_limit_max_requests=2, upload_rate_limit_window_seconds=60.0)
        pdf_bytes = build_pdf()

        _upload(client, pdf_bytes)
        _upload(client, pdf_bytes)
        third = _upload(client, pdf_bytes)

        assert third.status_code == 429
        body = third.json()
        assert body["error"]["code"] == ErrorCode.RATE_LIMITED.value
        assert "request_id" in body["error"]
        # Never a raw exception, internal detail, or the rate-limit
        # threshold itself (which would help an attacker tune around it).
        assert "20" not in body["error"]["user_message"]
        assert "InMemoryRateLimiter" not in body["error"]["user_message"]

    def test_rate_limit_does_not_prevent_a_third_party_from_reading_a_report(self, make_client, db_session):
        """The rate limiter only guards the expensive upload endpoint --
        confirms it isn't accidentally wired somewhere it would block
        ordinary report reads for a legitimate, already-uploaded document."""
        import uuid

        from app.models import db_models
        from tests.conftest import make_document

        client = make_client(upload_rate_limit_max_requests=1, upload_rate_limit_window_seconds=60.0)
        pdf_bytes = build_pdf()
        _upload(client, pdf_bytes)
        rate_limited = _upload(client, pdf_bytes)
        assert rate_limited.status_code == 429

        doc = make_document(access_token="z" * 64)
        db_session.add(doc)
        db_session.add(
            db_models.ProcessingJob(
                id=uuid.uuid4(), document_id=doc.id, stage=db_models.ProcessingStage.COMPLETED
            )
        )
        db_session.flush()

        report = client.get(
            f"/v1/documents/{doc.id}/report", headers={"Authorization": f"Bearer {doc.access_token}"}
        )
        assert report.status_code == 200


class TestProxyIpResolution:
    """Phase 11 — `resolve_client_ip` (docs/PROVISIONAL_DECISIONS.md P11.5).
    `X-Forwarded-For` is attacker-controlled input and must never be
    honored unless a deployment explicitly configures `trust_proxy_headers`.
    Starlette's `TestClient` always reports the same fixed direct-peer IP
    ("testclient") for every request, so these tests distinguish "trusted"
    vs "ignored" `X-Forwarded-For` handling by whether *that* header value
    is allowed to split requests into separate rate-limit buckets.
    """

    def test_x_forwarded_for_is_ignored_by_default(self, make_client):
        client = make_client(upload_rate_limit_max_requests=1, upload_rate_limit_window_seconds=60.0)
        pdf_bytes = build_pdf()

        first = _upload(client, pdf_bytes)
        assert first.status_code == 201

        # A different claimed X-Forwarded-For does not open a new bucket:
        # trust_proxy_headers defaults to False, so the header is never
        # even read, and both requests are keyed by the same direct peer
        # address.
        second = client.post(
            "/v1/documents",
            files={"file": ("contract.pdf", pdf_bytes, "application/pdf")},
            headers={"X-Forwarded-For": "203.0.113.5"},
        )
        assert second.status_code == 429

    def test_trusted_proxy_header_differentiates_clients(self, make_client):
        client = make_client(
            upload_rate_limit_max_requests=1, upload_rate_limit_window_seconds=60.0, trust_proxy_headers=True
        )
        pdf_bytes = build_pdf()

        first = client.post(
            "/v1/documents",
            files={"file": ("contract.pdf", pdf_bytes, "application/pdf")},
            headers={"X-Forwarded-For": "203.0.113.5"},
        )
        assert first.status_code == 201

        # A genuinely different (trusted, since trust_proxy_headers=True)
        # forwarded IP gets its own bucket -- not blocked by client A's
        # exhausted limit.
        second = client.post(
            "/v1/documents",
            files={"file": ("contract.pdf", pdf_bytes, "application/pdf")},
            headers={"X-Forwarded-For": "203.0.113.9"},
        )
        assert second.status_code == 201

        # Same forwarded IP as the first request -- shares its bucket, now
        # exhausted.
        third = client.post(
            "/v1/documents",
            files={"file": ("contract.pdf", pdf_bytes, "application/pdf")},
            headers={"X-Forwarded-For": "203.0.113.5"},
        )
        assert third.status_code == 429

    def test_only_the_rightmost_forwarded_entry_is_trusted(self, make_client):
        # Simulates exactly one trusted proxy hop: the proxy appends the
        # peer address *it* observed to the end of the list. Everything to
        # the left (including a value an attacker set directly) must be
        # ignored -- two requests with different attacker-supplied leftmost
        # values but the same proxy-appended rightmost value must share one
        # bucket.
        client = make_client(
            upload_rate_limit_max_requests=1, upload_rate_limit_window_seconds=60.0, trust_proxy_headers=True
        )
        pdf_bytes = build_pdf()

        first = client.post(
            "/v1/documents",
            files={"file": ("contract.pdf", pdf_bytes, "application/pdf")},
            headers={"X-Forwarded-For": "1.2.3.4, 203.0.113.5"},
        )
        assert first.status_code == 201

        second = client.post(
            "/v1/documents",
            files={"file": ("contract.pdf", pdf_bytes, "application/pdf")},
            headers={"X-Forwarded-For": "9.9.9.9, 203.0.113.5"},
        )
        assert second.status_code == 429

    def test_missing_header_falls_back_to_direct_peer_even_when_trusted(self, make_client):
        client = make_client(
            upload_rate_limit_max_requests=1, upload_rate_limit_window_seconds=60.0, trust_proxy_headers=True
        )
        pdf_bytes = build_pdf()

        first = _upload(client, pdf_bytes)
        assert first.status_code == 201
        second = _upload(client, pdf_bytes)
        assert second.status_code == 429
