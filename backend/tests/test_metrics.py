"""Operational metrics — Phase 11.

Verifies `GET /metrics` reports safe aggregates (never per-document
content) and that the counters actually move when the events they describe
happen: an upload, a completed pipeline job, a rate-limit rejection, and a
retention cleanup run.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import cast

from app.core.metrics import metrics, reset_metrics
from app.models.enums import DocumentType, RiskLevel
from app.services.generation_pipeline_service import generate_pending_explanations
from app.services.retention_service import run_retention_cleanup
from tests.conftest import make_clause, make_clause_analysis, make_document
from tests.fixtures.synthetic_documents import build_pdf


def _counters() -> dict[str, int]:
    # `MetricsRegistry.snapshot()` returns `dict[str, object]` (its two
    # keys, "counters"/"durations", hold differently-shaped values) --
    # this narrows the "counters" half back to its real shape for tests
    # that only need that half, rather than scattering `cast()` calls.
    return cast("dict[str, int]", metrics.snapshot()["counters"])


def _upload_pdf(client):
    return client.post(
        "/v1/documents",
        files={"file": ("contract.pdf", build_pdf(), "application/pdf")},
    )


class TestMetricsEndpoint:
    def test_starts_at_zero_after_reset(self, make_client):
        make_client()
        body = metrics.snapshot()
        assert body["counters"] == {}
        assert body["durations"] == {}

    def test_response_shape(self, make_client):
        client = make_client()
        response = client.get("/metrics")
        assert response.status_code == 200
        body = response.json()
        assert set(body.keys()) == {"counters", "durations"}

    def test_does_not_leak_internal_details(self, make_client):
        client = make_client()
        _upload_pdf(client)
        response = client.get("/metrics")
        text = response.text.lower()
        for forbidden in ("secret", "password", "database_url", "api_key", "traceback", "c:\\", "/users/"):
            assert forbidden not in text

    def test_upload_increments_documents_uploaded(self, make_client):
        client = make_client()
        response = _upload_pdf(client)
        assert response.status_code == 201

        counters = client.get("/metrics").json()["counters"]
        assert counters["documents_uploaded"] == 1

    def test_completed_pipeline_run_increments_completed_and_records_duration(self, make_client):
        client = make_client()
        response = _upload_pdf(client)
        assert response.status_code == 201
        document_id = response.json()["document_id"]
        access_token = response.json()["access_token"]

        status_response = client.get(
            f"/v1/documents/{document_id}/status", headers={"Authorization": f"Bearer {access_token}"}
        )
        assert status_response.json()["stage"] == "completed"

        body = client.get("/metrics").json()
        assert body["counters"]["pipeline_jobs_completed"] == 1
        duration = body["durations"]["pipeline_job_duration_seconds"]
        assert duration["count"] == 1
        assert duration["total_seconds"] >= 0.0

    def test_generation_without_a_configured_llm_client_increments_generation_failures(
        self, db_session, settings
    ):
        # No `client` is passed and `settings` carries no Anthropic API key,
        # so `build_llm_client` fails to resolve a client for the one
        # eligible HIGH clause -- a real, deterministic way to exercise the
        # generation-failure counter without a live or even a scripted-fake
        # LLM call.
        reset_metrics()
        document = make_document()
        db_session.add(document)
        db_session.flush()
        clause = make_clause(document_id=document.id)
        db_session.add(clause)
        db_session.flush()
        analysis = make_clause_analysis(clause_id=clause.id, risk_level=RiskLevel.HIGH, risk_score=0.9)
        db_session.add(analysis)
        db_session.commit()

        generate_pending_explanations(
            db_session, document.id, document_type=DocumentType.LOAN, settings=settings, client=None
        )

        assert _counters().get("explanations_generation_failed", 0) == 1

    def test_upload_rate_limit_rejection_increments_counter(self, make_client):
        client = make_client(upload_rate_limit_max_requests=1)
        first = _upload_pdf(client)
        assert first.status_code == 201
        second = _upload_pdf(client)
        assert second.status_code == 429

        counters = client.get("/metrics").json()["counters"]
        assert counters["upload_rate_limit_rejections"] == 1

    def test_retention_cleanup_increments_deleted_and_run_counters(self, make_client, db_session):
        make_client()
        now = datetime.now(UTC)
        document = make_document(access_token="z" * 64, created_at=now - timedelta(days=200))
        db_session.add(document)
        db_session.commit()

        run_retention_cleanup(db_session, retention_days=90, upload_dir="/nonexistent", now=now)
        db_session.commit()

        snapshot = _counters()
        assert snapshot["retention_documents_deleted"] == 1
        assert snapshot["retention_cleanup_runs"] == 1
