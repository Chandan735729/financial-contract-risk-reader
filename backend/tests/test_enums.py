"""Enum value/serialization tests — API_and_Data_Models.md SS1."""

from __future__ import annotations

import json

import pytest

from app.models.enums import (
    ConfidenceLevel,
    DocumentType,
    ErrorCode,
    ProcessingStage,
    RiskCategory,
    RiskLevel,
)


def test_risk_category_values_match_spec():
    assert {member.value for member in RiskCategory} == {
        "financial_cost",
        "default",
        "renewal",
        "loss_of_rights",
        "insurance",
        "interest_repayment",
        "termination",
        "other",
    }


def test_risk_level_values_match_spec():
    assert [m.value for m in RiskLevel] == ["HIGH", "MEDIUM", "LOW", "UNKNOWN"]


def test_confidence_level_values_match_spec():
    assert [m.value for m in ConfidenceLevel] == ["HIGH", "MEDIUM", "LOW"]


def test_document_type_values_match_spec():
    assert [m.value for m in DocumentType] == ["loan", "insurance", "unknown"]


def test_processing_stage_values_match_spec():
    assert [m.value for m in ProcessingStage] == [
        "queued",
        "parsing",
        "segmenting",
        "understanding",
        "scoring",
        "generating",
        "verifying",
        "completed",
        "failed",
    ]


def test_error_code_values_match_spec():
    assert {m.value for m in ErrorCode} == {
        "file_too_large",
        "unsupported_file_type",
        "corrupted_file",
        "password_protected",
        "low_text_content",
        "segmentation_low_confidence",
        "generation_failed",
        "grounding_failed",
        "access_denied",
        "rate_limited",
        "internal_error",
    }


def test_enums_are_json_serializable_as_plain_strings():
    # Every canonical enum is `str, Enum` so it serializes as its value, not
    # as `RiskLevel.HIGH` — required for clean JSON API payloads.
    assert json.dumps(RiskLevel.HIGH) == '"HIGH"'
    assert json.dumps(DocumentType.LOAN) == '"loan"'


def test_invalid_risk_level_value_rejected():
    with pytest.raises(ValueError):
        RiskLevel("not_a_real_level")


def test_invalid_risk_category_value_rejected():
    with pytest.raises(ValueError):
        RiskCategory("not_a_real_category")


def test_enum_values_are_case_sensitive():
    # "high" must not silently coerce to RiskLevel.HIGH — case is part of
    # the canonical value, not a formatting detail (API_and_Data_Models.md SS1).
    with pytest.raises(ValueError):
        RiskLevel("high")
