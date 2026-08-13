import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { RiskLevel } from "@/types/enums";
import { RiskBadge } from "./RiskBadge";

describe("RiskBadge", () => {
  it.each([
    [RiskLevel.HIGH, "High risk"],
    [RiskLevel.MEDIUM, "Medium risk"],
    [RiskLevel.LOW, "Low risk"],
    [RiskLevel.UNKNOWN, "Unknown"],
  ])("renders a visible text label for %s", (level, expectedText) => {
    render(<RiskBadge level={level} />);
    expect(screen.getByText(expectedText)).toBeInTheDocument();
  });

  it("UNKNOWN never reuses the check/warning/alert glyphs used by the other levels", () => {
    const { container: unknownContainer } = render(<RiskBadge level={RiskLevel.UNKNOWN} />);
    const { container: lowContainer } = render(<RiskBadge level={RiskLevel.LOW} />);
    const { container: mediumContainer } = render(<RiskBadge level={RiskLevel.MEDIUM} />);
    const { container: highContainer } = render(<RiskBadge level={RiskLevel.HIGH} />);

    const unknownGlyph = unknownContainer.querySelector("[aria-hidden]")?.textContent;
    const otherGlyphs = [lowContainer, mediumContainer, highContainer].map(
      (c) => c.querySelector("[aria-hidden]")?.textContent,
    );
    expect(otherGlyphs).not.toContain(unknownGlyph);
  });
});
