import { describe, expect, it } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ConfidenceLevel, DocumentType, RiskCategory, RiskLevel } from "@/types/enums";
import type { Clause, DocumentReport } from "@/types/clauseAnalysis";
import { ReportView } from "./ReportView";

function makeClause(index: number, level: RiskLevel, category: RiskCategory = RiskCategory.FINANCIAL_COST): Clause {
  return {
    clause_id: `clause-${index}`,
    clause_index: index,
    section_heading: `Clause ${index}`,
    raw_text: `Raw text for clause ${index}.`,
    analysis:
      level === RiskLevel.UNKNOWN
        ? {
            risk_category: null,
            risk_subcategory: null,
            taxonomy_version: "taxonomy_v1",
            trigger: null,
            condition: null,
            consequence: null,
            affected_party: null,
            risk_level: RiskLevel.UNKNOWN,
            risk_score: 0,
            confidence_level: ConfidenceLevel.LOW,
            confidence_score: 0.3,
            abstained: true,
            abstain_reason: "No signal found.",
            financial_entities: [],
            evidence_spans: [],
            explanation: null,
            explanation_grounded: null,
            model_version: "unscored",
            engine_version: "risk_engine_v1",
          }
        : {
            risk_category: category,
            risk_subcategory: null,
            taxonomy_version: "taxonomy_v1",
            trigger: null,
            condition: null,
            consequence: null,
            affected_party: null,
            risk_level: level,
            risk_score: 0.5,
            confidence_level: ConfidenceLevel.MEDIUM,
            confidence_score: 0.6,
            abstained: false,
            abstain_reason: null,
            financial_entities: [],
            evidence_spans: level === RiskLevel.LOW ? [] : [{ text: "evidence", start_char: 0, end_char: 8, page_number: null, verified: true }],
            explanation: null,
            explanation_grounded: null,
            model_version: "generation_skipped",
            engine_version: "risk_engine_v1",
          },
  };
}

function makeReport(): DocumentReport {
  const clauses = [
    makeClause(0, RiskLevel.HIGH),
    makeClause(1, RiskLevel.MEDIUM),
    makeClause(2, RiskLevel.LOW),
    makeClause(3, RiskLevel.UNKNOWN),
  ];
  return {
    document_id: "doc-1",
    document_type: DocumentType.LOAN,
    summary: { high: 1, medium: 1, low: 1, unknown: 1 },
    clauses,
  };
}

describe("ReportView", () => {
  it("shows all four summary counts, unknown never merged into low", () => {
    render(<ReportView report={makeReport()} />);
    const summary = screen.getByRole("region", { name: /summary/i });
    expect(summary).toHaveTextContent("1");
    const tileList = summary.querySelector("ul");
    expect(tileList).not.toBeNull();
    expect(within(tileList as HTMLElement).getByText("High")).toBeInTheDocument();
    expect(within(tileList as HTMLElement).getByText("Medium")).toBeInTheDocument();
    expect(within(tileList as HTMLElement).getByText("Low")).toBeInTheDocument();
    expect(within(tileList as HTMLElement).getByText("Unknown")).toBeInTheDocument();
  });

  it("default view shows HIGH/MEDIUM and UNKNOWN, but not LOW", () => {
    render(<ReportView report={makeReport()} />);
    expect(screen.getByRole("heading", { name: "Flagged clauses" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Needs review" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Low risk" })).not.toBeInTheDocument();
  });

  it("UNKNOWN is rendered in its own section, not interleaved with flagged clauses", () => {
    render(<ReportView report={makeReport()} />);
    const flaggedSection = screen.getByRole("heading", { name: "Flagged clauses" }).closest("section");
    const unknownSection = screen.getByRole("heading", { name: "Needs review" }).closest("section");
    expect(flaggedSection).not.toBe(unknownSection);
    expect(flaggedSection).not.toHaveTextContent("Unknown");
  });

  it("checking the LOW filter reveals the low-risk section", async () => {
    const user = userEvent.setup();
    render(<ReportView report={makeReport()} />);
    await user.click(screen.getByLabelText("Low"));
    expect(screen.getByRole("heading", { name: "Low risk" })).toBeInTheDocument();
  });

  it("unchecking HIGH hides the flagged section's HIGH clause but keeps MEDIUM", async () => {
    const user = userEvent.setup();
    render(<ReportView report={makeReport()} />);
    await user.click(screen.getByLabelText("High"));
    const flaggedSection = screen.getByRole("heading", { name: "Flagged clauses" }).closest("section");
    expect(flaggedSection).toHaveTextContent("Medium risk");
    expect(flaggedSection).not.toHaveTextContent("High risk");
  });

  it("filtering by category narrows the visible clauses", async () => {
    const user = userEvent.setup();
    const report = makeReport();
    report.clauses.push(makeClause(4, RiskLevel.HIGH, RiskCategory.TERMINATION));
    report.summary.high = 2;
    render(<ReportView report={report} />);

    await user.selectOptions(screen.getByLabelText("Category"), "termination");
    expect(screen.getByText("Clause 4")).toBeInTheDocument();
    expect(screen.queryByText("Clause 0")).not.toBeInTheDocument();
  });

  it("shows an empty state when no clauses match the current filters", async () => {
    const user = userEvent.setup();
    render(<ReportView report={makeReport()} />);
    await user.click(screen.getByLabelText("High"));
    await user.click(screen.getByLabelText("Medium"));
    await user.click(screen.getByLabelText("Unknown"));
    expect(screen.getByText("No clauses match the current filters.")).toBeInTheDocument();
  });

  it("renders the disclaimer without implying legal advice", () => {
    render(<ReportView report={makeReport()} />);
    expect(screen.getByText(/not legal advice/i)).toBeInTheDocument();
  });
});
