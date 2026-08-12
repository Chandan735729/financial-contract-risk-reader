"""Canonical enums — API_and_Data_Models.md SS1.

This module is the single Python source of truth for these enums. They are
mirrored (not generated) in TypeScript at
`frontend/src/types/enums.ts` — see that file's header comment for the
duplication strategy and `backend/tests/test_enum_ts_consistency.py` for the
automated cross-check that keeps the two from drifting silently.

Values (not just member names) must match `API_and_Data_Models.md` SS1
exactly, since these values round-trip through the database, the API JSON
payloads, and the frontend.
"""

from __future__ import annotations

from enum import Enum


class RiskCategory(str, Enum):
    FINANCIAL_COST = "financial_cost"
    DEFAULT = "default"
    RENEWAL = "renewal"
    LOSS_OF_RIGHTS = "loss_of_rights"
    INSURANCE = "insurance"
    INTEREST_REPAYMENT = "interest_repayment"
    TERMINATION = "termination"
    OTHER = "other"


class RiskLevel(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    UNKNOWN = "UNKNOWN"


class ConfidenceLevel(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class DocumentType(str, Enum):
    LOAN = "loan"
    INSURANCE = "insurance"
    UNKNOWN = "unknown"


class ProcessingStage(str, Enum):
    QUEUED = "queued"
    PARSING = "parsing"
    SEGMENTING = "segmenting"
    UNDERSTANDING = "understanding"
    SCORING = "scoring"
    GENERATING = "generating"
    VERIFYING = "verifying"
    COMPLETED = "completed"
    FAILED = "failed"


class ErrorCode(str, Enum):
    FILE_TOO_LARGE = "file_too_large"
    UNSUPPORTED_FILE_TYPE = "unsupported_file_type"
    CORRUPTED_FILE = "corrupted_file"
    PASSWORD_PROTECTED = "password_protected"
    LOW_TEXT_CONTENT = "low_text_content"
    SEGMENTATION_LOW_CONFIDENCE = "segmentation_low_confidence"
    GENERATION_FAILED = "generation_failed"
    GROUNDING_FAILED = "grounding_failed"
    ACCESS_DENIED = "access_denied"
    RATE_LIMITED = "rate_limited"
    INTERNAL_ERROR = "internal_error"
