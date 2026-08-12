// Canonical enums — API_and_Data_Models.md §1.
//
// SOURCE OF TRUTH: backend/app/models/enums.py. This file is a manual
// mirror, not generated. Duplication strategy (Phase 0 decision, not a
// v1-gap): a full codegen pipeline (e.g. datamodel-code-generator or
// openapi-typescript) is not yet justified for six small enums and would
// add build-tooling complexity before there's a real OpenAPI schema to
// generate from. Instead:
//   1. Both files carry this header pointing at each other.
//   2. backend/tests/test_enum_ts_consistency.py parses this file as text
//      and asserts every Python enum value appears in the matching
//      TypeScript enum block, so drift fails CI instead of failing silently.
// Revisit codegen once real API endpoints (Phase 6+) make an OpenAPI schema
// available to generate both sides from.

export enum RiskCategory {
  FINANCIAL_COST = "financial_cost",
  DEFAULT = "default",
  RENEWAL = "renewal",
  LOSS_OF_RIGHTS = "loss_of_rights",
  INSURANCE = "insurance",
  INTEREST_REPAYMENT = "interest_repayment",
  TERMINATION = "termination",
  OTHER = "other",
}

export enum RiskLevel {
  HIGH = "HIGH",
  MEDIUM = "MEDIUM",
  LOW = "LOW",
  UNKNOWN = "UNKNOWN",
}

export enum ConfidenceLevel {
  HIGH = "HIGH",
  MEDIUM = "MEDIUM",
  LOW = "LOW",
}

export enum DocumentType {
  LOAN = "loan",
  INSURANCE = "insurance",
  UNKNOWN = "unknown",
}

export enum ProcessingStage {
  QUEUED = "queued",
  PARSING = "parsing",
  SEGMENTING = "segmenting",
  UNDERSTANDING = "understanding",
  SCORING = "scoring",
  GENERATING = "generating",
  VERIFYING = "verifying",
  COMPLETED = "completed",
  FAILED = "failed",
}

export enum ErrorCode {
  FILE_TOO_LARGE = "file_too_large",
  UNSUPPORTED_FILE_TYPE = "unsupported_file_type",
  CORRUPTED_FILE = "corrupted_file",
  PASSWORD_PROTECTED = "password_protected",
  LOW_TEXT_CONTENT = "low_text_content",
  SEGMENTATION_LOW_CONFIDENCE = "segmentation_low_confidence",
  GENERATION_FAILED = "generation_failed",
  GROUNDING_FAILED = "grounding_failed",
  ACCESS_DENIED = "access_denied",
  RATE_LIMITED = "rate_limited",
  INTERNAL_ERROR = "internal_error",
}
