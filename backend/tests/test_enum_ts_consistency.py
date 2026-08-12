"""Cross-language enum consistency check.

Python (`app/models/enums.py`) is the canonical source; TypeScript
(`frontend/src/types/enums.ts`) is a manually-maintained mirror (see that
file's header for the duplication-strategy rationale). This test parses the
TypeScript file as plain text — no Node/TS toolchain required — and asserts
every Python enum value appears in the matching TS `enum` block, so drift
between the two fails a backend-only test run instead of going unnoticed.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.models.enums import (
    ConfidenceLevel,
    DocumentType,
    ErrorCode,
    ProcessingStage,
    RiskCategory,
    RiskLevel,
)

FRONTEND_ENUMS_PATH = Path(__file__).resolve().parents[2] / "frontend" / "src" / "types" / "enums.ts"

ENUM_CLASSES = [
    RiskCategory,
    RiskLevel,
    ConfidenceLevel,
    DocumentType,
    ProcessingStage,
    ErrorCode,
]


def _extract_ts_enum_block(source: str, enum_name: str) -> str:
    match = re.search(rf"export enum {enum_name}\s*{{(.*?)}}", source, re.DOTALL)
    assert match is not None, f"Could not find `export enum {enum_name}` block in {FRONTEND_ENUMS_PATH}"
    return match.group(1)


def _extract_ts_enum_values(block: str) -> set[str]:
    return set(re.findall(r'=\s*"([^"]+)"', block))


@pytest.fixture(scope="module")
def frontend_enums_source() -> str:
    assert FRONTEND_ENUMS_PATH.exists(), f"Expected TypeScript enums file at {FRONTEND_ENUMS_PATH}"
    return FRONTEND_ENUMS_PATH.read_text(encoding="utf-8")


@pytest.mark.parametrize("enum_cls", ENUM_CLASSES, ids=[c.__name__ for c in ENUM_CLASSES])
def test_python_enum_values_match_typescript_mirror(enum_cls, frontend_enums_source: str):
    block = _extract_ts_enum_block(frontend_enums_source, enum_cls.__name__)
    ts_values = _extract_ts_enum_values(block)
    py_values = {member.value for member in enum_cls}
    assert py_values == ts_values, (
        f"{enum_cls.__name__} drift between backend/app/models/enums.py and "
        f"frontend/src/types/enums.ts: python-only={py_values - ts_values}, "
        f"typescript-only={ts_values - py_values}"
    )
