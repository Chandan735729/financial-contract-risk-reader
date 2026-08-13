import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { ConfidenceLevel } from "@/types/enums";
import { ConfidenceIndicator } from "./ConfidenceIndicator";

describe("ConfidenceIndicator", () => {
  it("shows the confidence label, distinct from any risk badge", () => {
    render(<ConfidenceIndicator level={ConfidenceLevel.HIGH} score={0.92} />);
    expect(screen.getByText("Confidence: High")).toBeInTheDocument();
  });

  it.each([ConfidenceLevel.HIGH, ConfidenceLevel.MEDIUM, ConfidenceLevel.LOW])(
    "never uses a risk color token for %s",
    (level) => {
      const { container } = render(<ConfidenceIndicator level={level} score={0.5} />);
      const html = container.innerHTML;
      // Confidence must render via CSS module classes only, never an
      // inline style referencing a risk-* custom property (Frontend_
      // Specification_v2.md §3).
      expect(html).not.toMatch(/--risk-(red|amber|green)/);
    },
  );
});
