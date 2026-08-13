import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

vi.mock("next/navigation", () => ({
  useParams: () => ({ id: "doc-1" }),
}));

const { getDocumentStatusMock, getDocumentReportMock } = vi.hoisted(() => ({
  getDocumentStatusMock: vi.fn(),
  getDocumentReportMock: vi.fn(),
}));

vi.mock("@/lib/apiClient", async () => {
  const actual = await vi.importActual<typeof import("@/lib/apiClient")>("@/lib/apiClient");
  return {
    ...actual,
    getDocumentStatus: getDocumentStatusMock,
    getDocumentReport: getDocumentReportMock,
  };
});

import { ApiRequestError } from "@/lib/apiClient";
import { setDocumentToken } from "@/lib/tokenStore";
import DocumentPage from "./page";

function statusResponse(stage: string, error: unknown = null) {
  return { document_id: "doc-1", document_type: "loan", document_type_confidence: null, stage, error };
}

const emptyReport = {
  document_id: "doc-1",
  document_type: "loan",
  summary: { high: 0, medium: 0, low: 0, unknown: 0 },
  clauses: [],
};

beforeEach(() => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
});

afterEach(() => {
  vi.clearAllMocks();
  vi.useRealTimers();
  window.sessionStorage.clear();
});

describe("DocumentPage", () => {
  it("prompts for a token when none is stored for this document", async () => {
    render(<DocumentPage />);
    expect(await screen.findByText(/enter your access token/i)).toBeInTheDocument();
    expect(getDocumentStatusMock).not.toHaveBeenCalled();
  });

  it("submitting a token via the prompt starts polling", async () => {
    getDocumentStatusMock.mockResolvedValue(statusResponse("queued"));
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    render(<DocumentPage />);

    await user.type(await screen.findByLabelText(/enter your access token/i), "secret-token");
    await user.click(screen.getByRole("button", { name: "Continue" }));

    await waitFor(() => expect(getDocumentStatusMock).toHaveBeenCalledWith("doc-1", "secret-token"));
  });

  it("shows the processing view while the stage is not terminal, then the report once COMPLETED", async () => {
    setDocumentToken("doc-1", "tok");
    getDocumentStatusMock
      .mockResolvedValueOnce(statusResponse("segmenting"))
      .mockResolvedValueOnce(statusResponse("completed"));
    getDocumentReportMock.mockResolvedValue(emptyReport);

    render(<DocumentPage />);

    expect(await screen.findByText(/splitting into clauses/i)).toBeInTheDocument();

    await vi.advanceTimersByTimeAsync(3000);

    await waitFor(() => expect(getDocumentReportMock).toHaveBeenCalledWith("doc-1", "tok"));
    expect(await screen.findByText("Summary")).toBeInTheDocument();
  });

  it("shows a safe error message when the backend reports FAILED, never a raw error code", async () => {
    setDocumentToken("doc-1", "tok");
    getDocumentStatusMock.mockResolvedValue(
      statusResponse("failed", { code: "low_text_content", user_message: "We couldn't find enough readable text.", request_id: "req-1" }),
    );

    render(<DocumentPage />);

    expect(await screen.findByText("We couldn't find enough readable text.")).toBeInTheDocument();
    expect(screen.queryByText("low_text_content")).not.toBeInTheDocument();
  });

  it("shows the API's safe user message and a retry option on an authorization failure", async () => {
    setDocumentToken("doc-1", "tok");
    getDocumentStatusMock.mockRejectedValue(new ApiRequestError(401, "access_denied", "req-1"));

    render(<DocumentPage />);

    expect(await screen.findByText(/report isn't available/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument();
  });
});
