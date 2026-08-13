import { afterEach, describe, expect, it, vi } from "vitest";
import {
  ApiRequestError,
  getClauseEvidence,
  getDocumentReport,
  getDocumentStatus,
  uploadDocument,
} from "./apiClient";
import { ErrorCode } from "@/types/enums";
import { messageForCode } from "./errorMessages";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("uploadDocument", () => {
  it("POSTs multipart form data and returns the parsed response", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({ document_id: "doc-1", access_token: "secret-token" }, 201),
    );
    vi.stubGlobal("fetch", fetchMock);

    const file = new File(["contents"], "contract.pdf", { type: "application/pdf" });
    const result = await uploadDocument(file);

    expect(result).toEqual({ document_id: "doc-1", access_token: "secret-token" });
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain("/v1/documents");
    expect(init.method).toBe("POST");
    expect(init.body).toBeInstanceOf(FormData);
  });

  it("throws an ApiRequestError with the parsed envelope's code and the frontend's own copy for it", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse(
        { error: { code: "unsupported_file_type", user_message: "backend copy", request_id: "req-1" } },
        415,
      ),
    );
    vi.stubGlobal("fetch", fetchMock);

    const file = new File(["contents"], "contract.txt", { type: "text/plain" });
    await expect(uploadDocument(file)).rejects.toMatchObject({
      status: 415,
      code: "unsupported_file_type",
      requestId: "req-1",
      userMessage: messageForCode(ErrorCode.UNSUPPORTED_FILE_TYPE, 415),
    });
  });
});

describe("authorized reads", () => {
  it("getDocumentStatus sends the token as an Authorization header, never a query parameter", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({
        document_id: "doc-1",
        document_type: "loan",
        document_type_confidence: null,
        stage: "completed",
        error: null,
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await getDocumentStatus("doc-1", "secret-token");

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).not.toContain("secret-token");
    expect(url).toBe("http://localhost:8000/v1/documents/doc-1/status");
    const headers = init.headers as Record<string, string>;
    expect(headers.Authorization).toBe("Bearer secret-token");
  });

  it("getDocumentReport returns the parsed report", async () => {
    const report = { document_id: "doc-1", document_type: "loan", summary: { high: 1, medium: 0, low: 0, unknown: 0 }, clauses: [] };
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse(report)));
    await expect(getDocumentReport("doc-1", "tok")).resolves.toEqual(report);
  });

  it("getClauseEvidence hits the nested evidence route", async () => {
    const detail = { clause_id: "clause-1", evidence_spans: [], financial_entities: [], matched_patterns: [] };
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(detail));
    vi.stubGlobal("fetch", fetchMock);

    await getClauseEvidence("doc-1", "clause-1", "tok");

    const [url] = fetchMock.mock.calls[0] as [string];
    expect(url).toBe("http://localhost:8000/v1/documents/doc-1/clauses/clause-1/evidence");
  });
});

describe("error handling", () => {
  it("wraps a network-level failure in a generic ApiRequestError", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));
    await expect(getDocumentStatus("doc-1", "tok")).rejects.toBeInstanceOf(ApiRequestError);
    await expect(getDocumentStatus("doc-1", "tok")).rejects.toMatchObject({ status: 0 });
  });

  it("falls back to a status-based message when the error body isn't JSON", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response("<html>not json</html>", { status: 500 })),
    );
    await expect(getDocumentStatus("doc-1", "tok")).rejects.toMatchObject({
      status: 500,
      code: undefined,
    });
  });
});
