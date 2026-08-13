// Frontend end-to-end flow test (Phase 9 spec §24): upload -> processing ->
// report -> expand a HIGH clause -> inspect its evidence -> inspect its
// confidence -> inspect an UNKNOWN clause. Uses a controlled mock of
// `fetch` (the actual backend boundary), not per-function `apiClient`
// mocks, so this exercises the real request/response parsing path end to
// end, same as Phase 9 spec §24 asks for ("using a controlled test
// backend/mock"). Client-side routing (`next/navigation`) is mocked and
// the "navigation" is asserted directly on the pushed path string, which
// doubles as the "no token exposed in URL" check.

import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { UploadForm } from "@/components/UploadForm";
import DocumentPage from "@/app/documents/[id]/page";

const DOCUMENT_ID = "11111111-1111-1111-1111-111111111111";
const ACCESS_TOKEN = "e2e-secret-access-token";

const { pushMock, useParamsMock } = vi.hoisted(() => ({
  pushMock: vi.fn(),
  useParamsMock: vi.fn(() => ({ id: DOCUMENT_ID })),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: pushMock }),
  useParams: useParamsMock,
}));

const REPORT = {
  document_id: DOCUMENT_ID,
  document_type: "loan",
  summary: { high: 1, medium: 0, low: 0, unknown: 1 },
  clauses: [
    {
      clause_id: "clause-high",
      clause_index: 0,
      section_heading: "4. Prepayment",
      raw_text: "Borrower shall pay a prepayment penalty equal to 5% of the outstanding principal.",
      analysis: {
        risk_category: "financial_cost",
        risk_subcategory: "prepayment_penalty",
        taxonomy_version: "taxonomy_v1",
        trigger: null,
        condition: null,
        consequence: null,
        affected_party: null,
        risk_level: "HIGH",
        risk_score: 0.81,
        confidence_level: "HIGH",
        confidence_score: 0.92,
        abstained: false,
        abstain_reason: null,
        financial_entities: [{ type: "percentage", value: "5", unit: "%", raw_text: "5%" }],
        evidence_spans: [
          {
            text: "a prepayment penalty equal to 5% of the outstanding principal",
            start_char: 18,
            end_char: 79,
            page_number: 3,
            verified: true,
          },
        ],
        explanation: "This clause imposes a 5% prepayment penalty on the outstanding principal.",
        explanation_grounded: true,
        model_version: "claude-opus-5:prompt_v1",
        engine_version: "risk_engine_v1",
      },
    },
    {
      clause_id: "clause-unknown",
      clause_index: 1,
      section_heading: "9. General Provisions",
      raw_text: "Miscellaneous provisions may apply under certain circumstances.",
      analysis: {
        risk_category: null,
        risk_subcategory: null,
        taxonomy_version: "taxonomy_v1",
        trigger: null,
        condition: null,
        consequence: null,
        affected_party: null,
        risk_level: "UNKNOWN",
        risk_score: 0,
        confidence_level: "LOW",
        confidence_score: 0.35,
        abstained: true,
        abstain_reason: "No rule or corpus pattern matched this clause with sufficient confidence.",
        financial_entities: [],
        evidence_spans: [],
        explanation: null,
        explanation_grounded: null,
        model_version: "unscored",
        engine_version: "risk_engine_v1",
      },
    },
  ],
};

function mockFetch() {
  const statusCalls = { count: 0 };
  return vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === "string" ? input : input.toString();
    const headers = new Headers(init?.headers);

    if (url.endsWith("/v1/documents") && init?.method === "POST") {
      return new Response(
        JSON.stringify({ document_id: DOCUMENT_ID, access_token: ACCESS_TOKEN }),
        { status: 201, headers: { "Content-Type": "application/json" } },
      );
    }

    if (url.includes(`/v1/documents/${DOCUMENT_ID}/status`)) {
      expect(headers.get("Authorization")).toBe(`Bearer ${ACCESS_TOKEN}`);
      // Never a query parameter (Phase 9 spec §3).
      expect(url).not.toContain(ACCESS_TOKEN);
      statusCalls.count += 1;
      const stage = statusCalls.count === 1 ? "scoring" : "completed";
      return new Response(
        JSON.stringify({
          document_id: DOCUMENT_ID,
          document_type: "loan",
          document_type_confidence: null,
          stage,
          error: null,
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      );
    }

    if (url.includes(`/v1/documents/${DOCUMENT_ID}/report`)) {
      expect(headers.get("Authorization")).toBe(`Bearer ${ACCESS_TOKEN}`);
      expect(url).not.toContain(ACCESS_TOKEN);
      return new Response(JSON.stringify(REPORT), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    }

    throw new Error(`Unexpected fetch in e2e test: ${url}`);
  });
}

afterEach(() => {
  vi.clearAllMocks();
  vi.useRealTimers();
  window.sessionStorage.clear();
});

describe("upload -> processing -> report end-to-end flow", () => {
  it(
    "walks the full journey with a mocked backend, never exposing the token in a navigated URL",
    async () => {
    vi.stubGlobal("fetch", mockFetch());
    const user = userEvent.setup();

    // 1. Upload.
    const { unmount } = render(<UploadForm />);
    const file = new File([new Uint8Array(1024)], "contract.pdf", { type: "application/pdf" });
    const input = screen.getByLabelText("Choose a file", { selector: "input" });
    await user.upload(input, file);

    await waitFor(() => expect(pushMock).toHaveBeenCalledTimes(1));
    const [navigatedTo] = pushMock.mock.calls[0] as [string];
    expect(navigatedTo).toBe(`/documents/${DOCUMENT_ID}`);
    expect(navigatedTo).not.toContain(ACCESS_TOKEN);
    unmount();

    // 2. Processing -> report ("navigating" to the document page the
    // upload just redirected to). Real timers throughout this test --
    // the second poll genuinely waits out POLL_INTERVAL_MS in real time,
    // which is simpler and more reliable here than mixing fake timers
    // with React 19's own scheduler across a click interaction.
    render(<DocumentPage />);
    expect(await screen.findByText(/assessing risk/i)).toBeInTheDocument();
    expect(await screen.findByText("Summary", {}, { timeout: 5000 })).toBeInTheDocument();

    // 3. Expand the HIGH clause. Flagged (HIGH/MEDIUM) clauses render
    // pre-expanded by default (ReportView.tsx, Frontend_Specification_v2.md
    // §6: "HIGH and MEDIUM clauses shown first/expanded") -- so the real
    // user action this step exercises is collapse-then-re-expand via the
    // same toggle a user would click, not a first expand from nothing.
    const highToggle = await screen.findByRole("button", { name: /high risk/i });
    expect(highToggle).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText("Evidence")).toBeInTheDocument();

    await user.click(highToggle);
    expect(highToggle).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByText("Evidence")).not.toBeInTheDocument();

    await user.click(highToggle);
    expect(highToggle).toHaveAttribute("aria-expanded", "true");

    // 4. Inspect its evidence.
    expect(await screen.findByText("Evidence")).toBeInTheDocument();
    expect(screen.getAllByText(/prepayment penalty equal to/).length).toBeGreaterThan(0);
    expect(screen.getAllByText("5%").length).toBeGreaterThan(0);

    // 5. Inspect its confidence.
    expect(screen.getByText("Confidence: High")).toBeInTheDocument();

    // 6. Inspect the UNKNOWN clause -- collapsed by default (unlike the
    // flagged HIGH/MEDIUM section), so expand it first.
    const unknownToggle = screen.getByRole("button", { name: /unknown/i });
    expect(unknownToggle).toHaveAttribute("aria-expanded", "false");
    expect(screen.getByText("We couldn't find enough evidence to assess this clause confidently.")).toBeInTheDocument();

    await user.click(unknownToggle);

    expect(
      await screen.findByText("No rule or corpus pattern matched this clause with sufficient confidence."),
    ).toBeInTheDocument();
    expect(screen.queryByText(/probably fine/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/^safe$/i)).not.toBeInTheDocument();
    },
    10000,
  );
});
