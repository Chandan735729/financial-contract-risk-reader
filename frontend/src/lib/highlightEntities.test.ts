import { describe, expect, it } from "vitest";
import { highlightEntities } from "./highlightEntities";
import type { FinancialEntity } from "@/types/clauseAnalysis";

function entity(overrides: Partial<FinancialEntity>): FinancialEntity {
  return { type: "percentage", value: "5", unit: "%", raw_text: "5%", ...overrides };
}

describe("highlightEntities", () => {
  it("returns the whole text as one plain segment when there are no entities", () => {
    const segments = highlightEntities("Borrower may prepay at any time.", []);
    expect(segments).toEqual([{ text: "Borrower may prepay at any time.", isEntity: false }]);
  });

  it("splits out a single matching entity", () => {
    const segments = highlightEntities(
      "A penalty of 5% applies.",
      [entity({ raw_text: "5%" })],
    );
    expect(segments).toEqual([
      { text: "A penalty of ", isEntity: false },
      { text: "5%", isEntity: true, entityType: "percentage" },
      { text: " applies.", isEntity: false },
    ]);
  });

  it("does not highlight an entity whose raw_text is not present in the excerpt", () => {
    const segments = highlightEntities("No numbers here.", [entity({ raw_text: "5%" })]);
    expect(segments).toEqual([{ text: "No numbers here.", isEntity: false }]);
  });

  it("prefers the longer of two overlapping entity matches", () => {
    const segments = highlightEntities("within 24 months of disbursement", [
      entity({ raw_text: "24", type: "time_period" }),
      entity({ raw_text: "24 months", type: "time_period" }),
    ]);
    const entitySegments = segments.filter((s) => s.isEntity);
    expect(entitySegments).toHaveLength(1);
    expect(entitySegments[0]?.text).toBe("24 months");
  });

  it("highlights multiple non-overlapping entities in order", () => {
    const segments = highlightEntities("5% within 12 months", [
      entity({ raw_text: "5%", type: "percentage" }),
      entity({ raw_text: "12 months", type: "time_period" }),
    ]);
    expect(segments.filter((s) => s.isEntity).map((s) => s.text)).toEqual(["5%", "12 months"]);
  });

  it("ignores an entity with empty raw_text", () => {
    const segments = highlightEntities("Some text.", [entity({ raw_text: "" })]);
    expect(segments).toEqual([{ text: "Some text.", isEntity: false }]);
  });
});
