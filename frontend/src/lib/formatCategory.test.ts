import { describe, expect, it } from "vitest";
import { RiskCategory } from "@/types/enums";
import { formatCategory, formatSubcategory } from "./formatCategory";

describe("formatCategory", () => {
  it("formats every RiskCategory value to readable text", () => {
    for (const category of Object.values(RiskCategory)) {
      expect(formatCategory(category)).toBeTruthy();
    }
  });

  it("returns null for a null category", () => {
    expect(formatCategory(null)).toBeNull();
  });
});

describe("formatSubcategory", () => {
  it("title-cases a snake_case subcategory", () => {
    expect(formatSubcategory("prepayment_penalty")).toBe("Prepayment Penalty");
  });

  it("returns null for a null subcategory", () => {
    expect(formatSubcategory(null)).toBeNull();
  });
});
