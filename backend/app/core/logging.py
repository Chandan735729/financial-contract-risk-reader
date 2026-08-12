"""Structured, allowlist-based logging.

Security_and_Privacy_v2.md SS6 prohibits `raw_text`, `evidence_spans`
content, `financial_entities` values, `explanation` text, and PII-adjacent
data from ever reaching logs. Rather than trying to scrub arbitrary free-text
log messages after the fact, `log_event` only accepts a fixed allowlist of
field names — anything outside that allowlist is redacted, not silently
dropped, so a disallowed field is visible as a redaction rather than
vanishing without a trace (which would hide bugs).

Usage:
    logger = get_logger(__name__)
    log_event(logger, "clause_scored", document_id=doc_id, clause_id=clause_id,
               stage="scoring", risk_level="HIGH", confidence_score=0.92)
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any

# Fields explicitly safe to log per Security_and_Privacy_v2.md SS6:
# document ID, clause ID, stage name, risk_level, confidence_score, timing,
# and error type/category. Extended with a small set of equally-safe
# structural/versioning fields needed for operability.
ALLOWED_LOG_FIELDS: frozenset[str] = frozenset(
    {
        "document_id",
        "clause_id",
        "clause_analysis_id",
        "user_id",
        "request_id",
        "stage",
        "risk_level",
        "risk_score",
        "confidence_level",
        "confidence_score",
        "abstained",
        "taxonomy_version",
        "model_version",
        "engine_version",
        "error_code",
        "error_category",
        "http_method",
        "http_path",
        "status_code",
        "duration_ms",
        "count",
        "document_type",
        "environment",
        "low_confidence_flag",
        "segmentation_confidence",
    }
)

REDACTED_DISALLOWED = "[REDACTED:disallowed_field]"
REDACTED_TOO_LONG = "[REDACTED:value_too_long]"

# Defensive length cap even for allowed fields — allowed fields are expected
# to be short identifiers/enums/numbers, never document content. A long
# value in an allowed field most likely indicates a bug upstream (e.g. an
# id field accidentally holding a text blob), so it is redacted rather than
# trusted.
_MAX_SAFE_VALUE_LENGTH = 128


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "event": record.getMessage(),
            "logger": record.name,
        }
        fields = getattr(record, "fields", None)
        if fields:
            payload["fields"] = fields
        if record.exc_info:
            exc_type = record.exc_info[0]
            payload["exception_type"] = exc_type.__name__ if exc_type else None
        return json.dumps(payload, default=str)


def configure_logging(level: str = "INFO") -> None:
    """Configure the root logger with the JSON formatter.

    Idempotent: safe to call multiple times (e.g. once at app startup, once
    per test) without stacking duplicate handlers.
    """
    root = logging.getLogger()
    root.setLevel(level.upper())
    root.handlers.clear()

    handler = logging.StreamHandler(stream=sys.stdout)
    handler.setFormatter(_JsonFormatter())
    root.addHandler(handler)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


def _sanitize_value(value: Any) -> Any:
    if isinstance(value, str) and len(value) > _MAX_SAFE_VALUE_LENGTH:
        return REDACTED_TOO_LONG
    return value


def sanitize_fields(fields: dict[str, Any]) -> dict[str, Any]:
    """Apply the allowlist + length-cap redaction rules to a fields dict.

    Exposed separately from `log_event` so tests can assert on redaction
    behavior directly without needing to parse formatted log output.
    """
    safe: dict[str, Any] = {}
    for key, value in fields.items():
        if key not in ALLOWED_LOG_FIELDS:
            safe[key] = REDACTED_DISALLOWED
        else:
            safe[key] = _sanitize_value(value)
    return safe


def log_event(
    logger: logging.Logger,
    event: str,
    level: int = logging.INFO,
    **fields: Any,
) -> None:
    """Log a structured event with only allowlisted, redacted fields."""
    safe_fields = sanitize_fields(fields)
    logger.log(level, event, extra={"fields": safe_fields})
