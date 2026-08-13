// Deterministic ErrorCode -> user-facing copy (Phase 9 spec §21). Owned by
// the frontend, independently of the backend's own `user_message` (which
// `apiClient.ts` still uses as a fallback for a code this map doesn't
// recognize) — this is what lets the frontend guarantee its copy always
// matches the language policy (Security_and_Privacy_v2.md §7: never
// "illegal"/"invalid"/"unenforceable"/"you must", never a legal
// conclusion) even if a future backend message doesn't.
//
// Never includes exception text, stack traces, or any backend-internal
// detail (Phase 9 spec §17/§22) — every string here is static, pre-written
// UI copy.

import { ErrorCode } from "@/types/enums";

export const ERROR_CODE_MESSAGES: Record<ErrorCode, string> = {
  [ErrorCode.FILE_TOO_LARGE]:
    "This file is too large (or has too many pages) to process. Try a smaller file.",
  [ErrorCode.UNSUPPORTED_FILE_TYPE]: "Only PDF and DOCX files are supported.",
  [ErrorCode.CORRUPTED_FILE]: "This file could not be read. It may be corrupted or damaged.",
  [ErrorCode.PASSWORD_PROTECTED]:
    "This file is password-protected. Please upload an unprotected copy.",
  [ErrorCode.LOW_TEXT_CONTENT]:
    "We couldn't find enough readable text in this document — it may be a scanned or image-only file.",
  [ErrorCode.SEGMENTATION_LOW_CONFIDENCE]:
    "We couldn't reliably split this document into clauses. It may use an unusual layout or formatting.",
  [ErrorCode.GENERATION_FAILED]:
    "We couldn't generate a plain-language explanation for one or more clauses. The risk assessment and evidence below are still shown.",
  [ErrorCode.GROUNDING_FAILED]:
    "We couldn't verify a generated explanation against the source text, so it isn't shown. The risk assessment and evidence below are still shown.",
  [ErrorCode.ACCESS_DENIED]: "This report isn't available, or your access link is no longer valid.",
  [ErrorCode.RATE_LIMITED]: "Too many requests. Please wait a moment and try again.",
  [ErrorCode.INTERNAL_ERROR]: "Something went wrong on our end. Please try again.",
};

// Fallback for a raw HTTP status with no parsed error envelope at all (a
// network failure, or a response from something other than this API, e.g.
// a reverse proxy's own 413/502 page).
const STATUS_FALLBACK_MESSAGES: Partial<Record<number, string>> = {
  400: "We couldn't process that request. Please check the file and try again.",
  401: ERROR_CODE_MESSAGES[ErrorCode.ACCESS_DENIED],
  403: ERROR_CODE_MESSAGES[ErrorCode.ACCESS_DENIED],
  404: ERROR_CODE_MESSAGES[ErrorCode.ACCESS_DENIED],
  413: ERROR_CODE_MESSAGES[ErrorCode.FILE_TOO_LARGE],
  415: ERROR_CODE_MESSAGES[ErrorCode.UNSUPPORTED_FILE_TYPE],
  429: ERROR_CODE_MESSAGES[ErrorCode.RATE_LIMITED],
  500: ERROR_CODE_MESSAGES[ErrorCode.INTERNAL_ERROR],
  502: ERROR_CODE_MESSAGES[ErrorCode.INTERNAL_ERROR],
  503: ERROR_CODE_MESSAGES[ErrorCode.INTERNAL_ERROR],
};

export const GENERIC_FALLBACK_MESSAGE = "Something went wrong. Please try again.";

export function messageForStatus(status: number): string {
  return STATUS_FALLBACK_MESSAGES[status] ?? GENERIC_FALLBACK_MESSAGE;
}

export function messageForCode(code: string | undefined, status: number): string {
  if (code && code in ERROR_CODE_MESSAGES) {
    return ERROR_CODE_MESSAGES[code as ErrorCode];
  }
  return messageForStatus(status);
}
