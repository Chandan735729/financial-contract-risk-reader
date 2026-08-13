import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ConfidenceLevel, RiskCategory, RiskLevel } from "@/types/enums";
import type { Clause, ClauseAnalysis } from "@/types/clauseAnalysis";
import { ClauseCard } from "./ClauseCard";

function analysis(overrides: Partial<ClauseAnalysis> = {}): ClauseAnalysis {
  return {
    risk_category: RiskCategory.FINANCIAL_COST,
    risk_subcategory: "prepayment_penalty",
    taxonomy_version: "taxonomy_v1",
    trigger: null,
    condition: null,
    consequence: null,
    affected_party: null,
    risk_level: RiskLevel.HIGH,
    risk_score: 0.81,
    confidence_level: ConfidenceLevel.HIGH,
    confidence_score: 0.9,
    abstained: false,
    abstain_reason: null,
    financial_entities: [{ type: "percentage", value: "5", unit: "%", raw_text: "5%" }],
    evidence_spans: [
      { text: "a 5% prepayment penalty", start_char: 10, end_char: 34, page_number: 2, verified: true },
    ],
    explanation: "This clause imposes a 5% prepayment penalty.",
    explanation_grounded: true,
    model_version: "claude-opus-5:prompt_v1",
    engine_version: "risk_engine_v1",
    ...overrides,
  };
}

function clause(overrides: Partial<Clause> = {}): Clause {
  return {
    clause_id: "clause-1",
    clause_index: 0,
    section_heading: "4. Prepayment",
    raw_text: "Borrower shall pay a 5% prepayment penalty if repaid within 24 months.",
    analysis: analysis(),
    ...overrides,
  };
}

describe("ClauseCard", () => {
  it("is collapsed by default and expands on click", async () => {
    const user = userEvent.setup();
    render(<ClauseCard clause={clause()} />);

    expect(screen.queryByText("This clause imposes a 5% prepayment penalty.")).not.toBeInTheDocument();

    const toggle = screen.getByRole("button", { expanded: false });
    await user.click(toggle);

    expect(screen.getByText("This clause imposes a 5% prepayment penalty.")).toBeInTheDocument();
    expect(screen.getByRole("button", { expanded: true })).toBeInTheDocument();
  });

  it("renders HIGH risk with its label and paired confidence", () => {
    render(<ClauseCard clause={clause({ analysis: analysis({ risk_level: RiskLevel.HIGH }) })} defaultExpanded />);
    expect(screen.getByText("High risk")).toBeInTheDocument();
    expect(screen.getByText("Confidence: High")).toBeInTheDocument();
  });

  it("renders MEDIUM risk", () => {
    render(
      <ClauseCard
        clause={clause({ analysis: analysis({ risk_level: RiskLevel.MEDIUM, confidence_level: ConfidenceLevel.MEDIUM }) })}
      />,
    );
    expect(screen.getByText("Medium risk")).toBeInTheDocument();
  });

  it("renders LOW risk with no explanation attempted", () => {
    render(
      <ClauseCard
        clause={clause({
          analysis: analysis({
            risk_level: RiskLevel.LOW,
            explanation: null,
            explanation_grounded: null,
            financial_entities: [],
            evidence_spans: [],
          }),
        })}
        defaultExpanded
      />,
    );
    expect(screen.getByText("Low risk")).toBeInTheDocument();
    expect(screen.queryByText(/couldn't generate a verified/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/wasn't generated for this clause/i)).not.toBeInTheDocument();
  });

  it("renders the UNKNOWN state with its abstain reason, never as 'safe' or 'low risk'", () => {
    render(
      <ClauseCard
        clause={clause({
          analysis: analysis({
            risk_level: RiskLevel.UNKNOWN,
            abstained: true,
            abstain_reason: "No matching rule or corpus pattern found for this clause.",
            confidence_level: ConfidenceLevel.LOW,
            explanation: null,
            explanation_grounded: null,
            evidence_spans: [],
            financial_entities: [],
          }),
        })}
        defaultExpanded
      />,
    );
    expect(screen.getByText("Unknown")).toBeInTheDocument();
    expect(screen.getByText("We couldn't find enough evidence to assess this clause confidently.")).toBeInTheDocument();
    expect(screen.getByText("No matching rule or corpus pattern found for this clause.")).toBeInTheDocument();
    expect(screen.queryByText(/safe/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/probably fine/i)).not.toBeInTheDocument();
  });

  it("shows the Grounding_and_Evidence_Spec.md §5 fallback message when grounding failed, and still shows evidence", () => {
    render(
      <ClauseCard
        clause={clause({
          analysis: analysis({
            risk_level: RiskLevel.MEDIUM,
            explanation: null,
            explanation_grounded: false,
          }),
        })}
        defaultExpanded
      />,
    );
    expect(
      screen.getByText(
        "We identified this as a MEDIUM financial cost concern based on the evidence below, but couldn't generate a verified plain-language explanation. Please review the original text.",
      ),
    ).toBeInTheDocument();
    expect(screen.getByText("Evidence")).toBeInTheDocument();
    expect(screen.getAllByText(/5%/).length).toBeGreaterThan(0);
  });

  it("shows a distinct message when generation was skipped (cost cap), not the grounding-failure message", () => {
    render(
      <ClauseCard
        clause={clause({
          analysis: analysis({
            risk_level: RiskLevel.HIGH,
            explanation: null,
            explanation_grounded: null,
          }),
        })}
        defaultExpanded
      />,
    );
    expect(screen.getByText(/wasn't generated for this clause/i)).toBeInTheDocument();
    expect(screen.queryByText(/couldn't generate a verified/i)).not.toBeInTheDocument();
  });

  it("never shows a blank/broken card when explanation is unavailable — risk, confidence, and evidence are still present", () => {
    render(
      <ClauseCard
        clause={clause({
          analysis: analysis({ risk_level: RiskLevel.HIGH, explanation: null, explanation_grounded: false }),
        })}
        defaultExpanded
      />,
    );
    expect(screen.getByText("High risk")).toBeInTheDocument();
    expect(screen.getByText("Confidence: High")).toBeInTheDocument();
    expect(screen.getByText("Evidence")).toBeInTheDocument();
  });

  it("renders the partial-failure state when analysis is null, without crashing the rest of the report", () => {
    render(<ClauseCard clause={clause({ analysis: null })} />);
    expect(screen.getByText(/couldn't be analyzed/i)).toBeInTheDocument();
  });

  it("highlights extracted financial entities inside the evidence excerpt", () => {
    render(<ClauseCard clause={clause()} defaultExpanded />);
    const marks = document.querySelectorAll("mark");
    expect(Array.from(marks).some((m) => m.textContent === "5%")).toBe(true);
  });
});
