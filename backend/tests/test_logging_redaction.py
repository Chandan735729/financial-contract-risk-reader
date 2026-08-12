"""Redaction tests — Security_and_Privacy_v2.md SS6.

Confirms disallowed fields (raw contract text, evidence text, entity
values, explanations, names, addresses, account numbers, tokens, keys) are
redacted before ever reaching a log line, and that allowed metadata fields
still pass through so logs remain useful.
"""

from __future__ import annotations

import json
import logging

import pytest

from app.core.logging import (
    ALLOWED_LOG_FIELDS,
    REDACTED_DISALLOWED,
    REDACTED_TOO_LONG,
    _JsonFormatter,
    log_event,
    sanitize_fields,
)

SENSITIVE_CONTRACT_TEXT = (
    "Borrower John Smith, account number 1234567890, residing at 42 Example "
    "Street, agrees to a prepayment penalty of 5% under this Agreement."
)


@pytest.mark.parametrize(
    "disallowed_field",
    [
        "raw_text",
        "clause_raw_text",
        "evidence_text",
        "evidence_span_text",
        "financial_entity_value",
        "explanation",
        "name",
        "address",
        "account_number",
        "access_token",
        "api_key",
        "authorization",
        "password",
        "uploaded_filename",
    ],
)
def test_disallowed_fields_are_redacted_not_logged(disallowed_field: str):
    result = sanitize_fields({disallowed_field: SENSITIVE_CONTRACT_TEXT})
    assert result[disallowed_field] == REDACTED_DISALLOWED
    assert SENSITIVE_CONTRACT_TEXT not in json.dumps(result)


def test_allowed_fields_pass_through():
    fields = {
        "document_id": "doc-123",
        "clause_id": "clause-456",
        "stage": "scoring",
        "risk_level": "HIGH",
        "confidence_score": 0.92,
        "engine_version": "engine-v0",
    }
    result = sanitize_fields(fields)
    assert result == fields


def test_every_allowed_field_is_a_safe_metadata_field():
    # Defensive: none of the explicitly-allowed fields should be named in a
    # way that suggests they'd hold document content.
    forbidden_substrings = ("text", "explanation", "raw_text", "value", "address")
    for field in ALLOWED_LOG_FIELDS:
        for bad in forbidden_substrings:
            assert bad not in field, f"{field!r} looks unsafe to allow in logs"


def test_overlong_allowed_value_is_redacted():
    long_value = "x" * 500
    result = sanitize_fields({"document_id": long_value})
    assert result["document_id"] == REDACTED_TOO_LONG


def test_log_event_end_to_end_never_emits_sensitive_text(caplog: pytest.LogCaptureFixture):
    logger = logging.getLogger("test.redaction")
    logger.setLevel(logging.INFO)

    with caplog.at_level(logging.INFO, logger="test.redaction"):
        log_event(
            logger,
            "clause_scored",
            document_id="doc-1",
            clause_id="clause-1",
            risk_level="HIGH",
            confidence_score=0.9,
            raw_text=SENSITIVE_CONTRACT_TEXT,
            explanation=SENSITIVE_CONTRACT_TEXT,
        )

    record = caplog.records[0]
    assert SENSITIVE_CONTRACT_TEXT not in record.getMessage()
    # `fields` is attached dynamically via `extra={"fields": ...}` in
    # log_event, not a stdlib LogRecord attribute — getattr() reads it
    # without asserting a static type stdlib doesn't declare.
    logged_fields = getattr(record, "fields")  # noqa: B009
    assert logged_fields["raw_text"] == REDACTED_DISALLOWED
    assert logged_fields["explanation"] == REDACTED_DISALLOWED
    assert logged_fields["risk_level"] == "HIGH"

    formatted = _JsonFormatter().format(record)
    assert SENSITIVE_CONTRACT_TEXT not in formatted
    payload = json.loads(formatted)
    assert payload["fields"]["raw_text"] == REDACTED_DISALLOWED
