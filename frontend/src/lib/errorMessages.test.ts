import { describe, expect, it } from "vitest";
import { ErrorCode } from "@/types/enums";
import { ERROR_CODE_MESSAGES, GENERIC_FALLBACK_MESSAGE, messageForCode, messageForStatus } from "./errorMessages";

describe("messageForCode", () => {
  it("returns the frontend-owned copy for every known ErrorCode", () => {
    for (const code of Object.values(ErrorCode)) {
      const message = messageForCode(code, 400);
      expect(message).toBe(ERROR_CODE_MESSAGES[code]);
      expect(message.length).toBeGreaterThan(0);
    }
  });

  it("never includes banned legal-conclusion language (Security_and_Privacy_v2.md §7)", () => {
    const banned = ["illegal", "invalid", "unlawful", "unenforceable", "you must", "you are required"];
    for (const message of Object.values(ERROR_CODE_MESSAGES)) {
      const lowered = message.toLowerCase();
      for (const phrase of banned) {
        expect(lowered).not.toContain(phrase);
      }
    }
  });

  it("falls back to the status-based message for an unrecognized code", () => {
    expect(messageForCode("some_future_code", 500)).toBe(messageForStatus(500));
  });

  it("falls back to the status-based message when code is undefined", () => {
    expect(messageForCode(undefined, 404)).toBe(messageForStatus(404));
  });
});

describe("messageForStatus", () => {
  it("maps known statuses deterministically", () => {
    expect(messageForStatus(413)).toBe(ERROR_CODE_MESSAGES[ErrorCode.FILE_TOO_LARGE]);
    expect(messageForStatus(429)).toBe(ERROR_CODE_MESSAGES[ErrorCode.RATE_LIMITED]);
  });

  it("falls back to a generic safe message for an unmapped status", () => {
    expect(messageForStatus(0)).toBe(GENERIC_FALLBACK_MESSAGE);
    expect(messageForStatus(999)).toBe(GENERIC_FALLBACK_MESSAGE);
  });
});
