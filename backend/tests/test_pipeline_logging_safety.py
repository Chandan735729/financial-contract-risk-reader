"""Proves the complete pipeline (upload -> parsing -> segmentation ->
understanding -> scoring -> generation) never leaks raw contract content,
entity values, generated explanations, or access tokens into logs -- Phase 8
spec: "add integration tests proving the complete pipeline doesn't leak
these values." Also proves per-stage timing is captured (Phase 8 spec:
"measure enough to identify obvious bottlenecks ... without logging raw
content while timing") using the same captured log stream.

`app.core.logging.log_event`'s allowlist (`ALLOWED_LOG_FIELDS`) already
defends against this structurally (see its unit tests in
`test_logging.py`); this test is the end-to-end regression guard that a real
pipeline run's *actual formatted log output* never contains a canary value,
catching any call site that bypassed `log_event` entirely (e.g. a stray
`logger.info(f"...{raw_text}...")`), not just a field-name mistake.
"""

from __future__ import annotations

import json
import logging

import pytest

from app.api.deps import get_llm_client as real_get_llm_client
from app.core.logging import _JsonFormatter
from app.main import app
from app.services.generation_service import _LLMClaim, _LLMGenerationOutput
from tests.fixtures.synthetic_documents import build_docx

_CLAUSE_CANARY = "CANARY-CLAUSE-CONTENT-QzR7"
_ENTITY_CANARY = "9.87"
_EXPLANATION_CANARY = "CANARY-EXPLANATION-TEXT-Vb3K"

_CLAUSE_TEXT = (
    f"Borrower shall pay a prepayment penalty equal to {_ENTITY_CANARY}% of the outstanding "
    f"principal if the loan is repaid within 24 months. {_CLAUSE_CANARY}."
)


class _FakeLLMClient:
    def generate_structured(self, *, system_prompt, user_prompt, output_schema, max_output_tokens):
        return _LLMGenerationOutput(
            explanation=f"{_EXPLANATION_CANARY}: a {_ENTITY_CANARY}% prepayment penalty applies.",
            claims=[
                _LLMClaim(
                    text=f"{_EXPLANATION_CANARY}: a {_ENTITY_CANARY}% prepayment penalty applies.",
                    type="fee",
                    supporting_evidence_ids=[],
                )
            ],
        )


class _CapturingHandler(logging.Handler):
    """Collects the exact formatted string every log record produces, via
    the real `_JsonFormatter` production uses -- not the raw `LogRecord`
    object, so this catches leaks in the formatting step too."""

    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.setFormatter(_JsonFormatter())
        self.lines: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.lines.append(self.format(record))


@pytest.fixture()
def captured_logs():
    handler = _CapturingHandler()
    root = logging.getLogger()
    root.addHandler(handler)
    previous_level = root.level
    root.setLevel(logging.DEBUG)
    try:
        yield handler
    finally:
        root.removeHandler(handler)
        root.setLevel(previous_level)


class TestPipelineLoggingSafety:
    def test_full_pipeline_run_never_logs_secret_content(self, make_client, captured_logs):
        client = make_client()
        app.dependency_overrides[real_get_llm_client] = lambda: _FakeLLMClient()

        data = build_docx(
            items=[
                ("Heading 1", "1. Prepayment"),
                ("Normal", _CLAUSE_TEXT),
                ("Heading 1", "2. Prepayment Rights"),
                ("Normal", "Borrower may prepay at any time without penalty."),
            ],
            include_table=False,
        )
        response = client.post(
            "/v1/documents",
            files={
                "file": (
                    "contract.docx",
                    data,
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                )
            },
        )
        assert response.status_code == 201
        body = response.json()
        document_id = body["document_id"]
        access_token = body["access_token"]

        # Also exercise the read endpoints -- their own request-handling
        # code (e.g. exception handlers logging `http_path`) must not leak
        # the token either. The token travels as an Authorization header,
        # not a query parameter, specifically because this test (in an
        # earlier form) caught the test HTTP client's own request logger
        # emitting the full URL -- a query-string token would have leaked
        # into any real access log the same way.
        auth_header = {"Authorization": f"Bearer {access_token}"}
        client.get(f"/v1/documents/{document_id}/report", headers=auth_header)
        client.get(f"/v1/documents/{document_id}/status", headers=auth_header)

        assert captured_logs.lines, "expected at least one log line to be captured"

        joined = "\n".join(captured_logs.lines)
        assert _CLAUSE_CANARY not in joined
        assert _ENTITY_CANARY not in joined
        assert _EXPLANATION_CANARY not in joined
        assert access_token not in joined
        # The clause's raw sentence as a whole must never appear either --
        # a narrower canary substring check alone wouldn't catch a bug that
        # logs a *different* fragment of the same clause text.
        assert _CLAUSE_TEXT not in joined

    def test_every_stage_logs_a_safe_numeric_duration(self, make_client, captured_logs):
        """Each of parsing/segmenting/understanding/scoring/generating, plus
        the overall pipeline, logs `duration_ms` -- a plain integer, never
        content -- so an obvious per-stage bottleneck is identifiable from
        logs alone."""
        client = make_client()
        app.dependency_overrides[real_get_llm_client] = lambda: _FakeLLMClient()

        data = build_docx(
            items=[
                ("Heading 1", "1. Prepayment"),
                ("Normal", _CLAUSE_TEXT),
                ("Heading 1", "2. Prepayment Rights"),
                ("Normal", "Borrower may prepay at any time without penalty."),
            ],
            include_table=False,
        )
        response = client.post(
            "/v1/documents",
            files={
                "file": (
                    "contract.docx",
                    data,
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                )
            },
        )
        assert response.status_code == 201

        records = [json.loads(line) for line in captured_logs.lines if line.strip().startswith("{")]
        stage_events = {
            r["fields"]["stage"]: r["fields"]["duration_ms"]
            for r in records
            if r.get("event") == "pipeline_stage_completed"
        }
        for stage in ("parsing", "segmenting", "understanding", "scoring", "generating"):
            assert stage in stage_events, f"missing timing for stage {stage!r}"
            assert isinstance(stage_events[stage], int)
            assert stage_events[stage] >= 0

        completed = next(r for r in records if r.get("event") == "pipeline_completed")
        assert isinstance(completed["fields"]["duration_ms"], int)
        assert completed["fields"]["duration_ms"] >= 0
