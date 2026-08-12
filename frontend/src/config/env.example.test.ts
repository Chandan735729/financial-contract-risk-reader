import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

// Security_and_Privacy_v2.md §5: backend secrets must never be readable by
// the frontend. Only NEXT_PUBLIC_* variables reach the browser bundle, so
// this pins the actual failure mode: a backend secret name accidentally
// declared in frontend/.env.example (with or without a NEXT_PUBLIC_ prefix).
const FORBIDDEN_PATTERNS = [/ANTHROPIC/i, /DATABASE_URL/i, /_SECRET/i, /_PASSWORD/i];

describe("frontend/.env.example", () => {
  const contents = readFileSync(resolve(__dirname, "../../.env.example"), "utf-8");
  // Only actual `KEY=value` declaration lines matter here — the file's own
  // comments legitimately name ANTHROPIC_API_KEY/DATABASE_URL as examples of
  // what must never be *declared* below.
  const declarations = contents.split("\n").filter((line) => line.includes("=") && !line.trim().startsWith("#"));

  it("does not declare any backend-only secret", () => {
    for (const line of declarations) {
      for (const pattern of FORBIDDEN_PATTERNS) {
        expect(line).not.toMatch(pattern);
      }
    }
  });

  it("only declares NEXT_PUBLIC_* variables", () => {
    for (const line of declarations) {
      expect(line.trim()).toMatch(/^NEXT_PUBLIC_/);
    }
  });
});
