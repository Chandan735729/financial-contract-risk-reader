// Typed frontend API client (Phase 9 spec §4). The only module that calls
// `fetch` against the backend — components/pages must go through this, so
// error handling, auth headers, and response typing stay in one place.
//
// The access token is always sent as `Authorization: Bearer <token>`
// (backend/app/api/deps.py::require_document_access), never a query
// parameter, and this module never logs a token, a URL containing one, or
// any response body content (Phase 9 spec §3/§22).

import { env } from "@/config/env";
import type {
  ApiError as ApiErrorEnvelope,
  DocumentUploadResponse,
  ProcessingStatus,
} from "@/types/api";
import type { ClauseEvidenceDetail, DocumentReport } from "@/types/clauseAnalysis";
import { messageForCode, messageForStatus } from "./errorMessages";

export class ApiRequestError extends Error {
  readonly status: number;
  readonly code: string | undefined;
  readonly requestId: string | undefined;
  /** Pre-computed, safe, user-facing copy — components should render this
   * directly and never construct their own message from `code`/`status`. */
  readonly userMessage: string;

  constructor(status: number, code: string | undefined, requestId: string | undefined) {
    const userMessage = messageForCode(code, status);
    super(userMessage);
    this.name = "ApiRequestError";
    this.status = status;
    this.code = code;
    this.requestId = requestId;
    this.userMessage = userMessage;
  }
}

function isApiErrorEnvelope(value: unknown): value is ApiErrorEnvelope {
  if (typeof value !== "object" || value === null || !("error" in value)) {
    return false;
  }
  const error = (value as { error: unknown }).error;
  return typeof error === "object" && error !== null && "code" in error;
}

async function parseErrorResponse(response: Response): Promise<ApiRequestError> {
  try {
    const body: unknown = await response.json();
    if (isApiErrorEnvelope(body)) {
      return new ApiRequestError(response.status, body.error.code, body.error.request_id);
    }
  } catch {
    // Response body wasn't valid JSON (e.g. a proxy's own error page) —
    // fall through to the status-only fallback below.
  }
  return new ApiRequestError(response.status, undefined, undefined);
}

interface RequestOptions {
  method?: "GET" | "POST";
  token?: string;
  body?: BodyInit;
  headers?: Record<string, string>;
}

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const headers: Record<string, string> = { ...options.headers };
  if (options.token) {
    headers.Authorization = `Bearer ${options.token}`;
  }

  let response: Response;
  try {
    response = await fetch(`${env.apiBaseUrl}${path}`, {
      method: options.method ?? "GET",
      headers,
      body: options.body,
    });
  } catch {
    // A network-level failure (offline, DNS, CORS, timeout) never carries a
    // parseable body — status 0 is a client-only sentinel, mapped to a
    // generic safe message by messageForStatus.
    throw new ApiRequestError(0, undefined, undefined);
  }

  if (!response.ok) {
    throw await parseErrorResponse(response);
  }

  return (await response.json()) as T;
}

export async function uploadDocument(file: File): Promise<DocumentUploadResponse> {
  const formData = new FormData();
  formData.append("file", file);
  return request<DocumentUploadResponse>("/v1/documents", { method: "POST", body: formData });
}

export async function getDocumentStatus(
  documentId: string,
  token: string,
): Promise<ProcessingStatus> {
  return request<ProcessingStatus>(`/v1/documents/${documentId}/status`, { token });
}

export async function getDocumentReport(
  documentId: string,
  token: string,
): Promise<DocumentReport> {
  return request<DocumentReport>(`/v1/documents/${documentId}/report`, { token });
}

export async function getClauseEvidence(
  documentId: string,
  clauseId: string,
  token: string,
): Promise<ClauseEvidenceDetail> {
  return request<ClauseEvidenceDetail>(`/v1/documents/${documentId}/clauses/${clauseId}/evidence`, {
    token,
  });
}

/** Re-exported so `messageForStatus` never needs a second import path. */
export { messageForStatus };
