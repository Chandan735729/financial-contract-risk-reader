import { describe, expect, it } from "vitest";
import type { ClauseEvidenceDetail } from "./clauseAnalysis";
import type { ClauseAnalysis } from "./clauseAnalysis";

describe("public ClauseAnalysis type", () => {
  it("does not expose matched_patterns (internal-only retrieval signal)", () => {
    const sample = {} as ClauseAnalysis;
    // @ts-expect-error matched_patterns is intentionally omitted from the
    // public API type (Technical_Architecture_v2.md §5: retrieval is
    // internal-only) — if this field is ever added back, `tsc --noEmit`
    // fails here with "Unused '@ts-expect-error' directive", catching the
    // regression at type-check time.
    void sample.matched_patterns;
    expect(true).toBe(true);
  });

  it("only exposes matched_patterns via the separate evidence drill-down type", () => {
    const detail = {} as ClauseEvidenceDetail;
    expect(detail.matched_patterns).toBeUndefined();
  });
});
