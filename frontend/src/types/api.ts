// Supporting public API types — API_and_Data_Models.md §3-4.

import type { DocumentType, ErrorCode, ProcessingStage } from "./enums";

/** Public document identity + classification — the fields common to every
 * document-scoped response. Mirrors the backend's public-safe projection of
 * the `documents` row: `access_token`, `storage_path`, `original_filename`,
 * and `user_id` are intentionally never part of this type — none of the
 * `/status` or `/report` response examples in API_and_Data_Models.md §3
 * include them. */
export interface Document {
  document_id: string;
  document_type: DocumentType;
  document_type_confidence: number | null;
}

/** `GET /documents/{id}/status` response (API_and_Data_Models.md §3). */
export interface ProcessingStatus extends Document {
  stage: ProcessingStage;
  error: ApiErrorDetail | null;
}

export interface ApiErrorDetail {
  code: ErrorCode;
  user_message: string;
  request_id: string;
}

export interface ApiError {
  error: ApiErrorDetail;
}

export interface HealthResponse {
  status: "ok";
  environment: string;
}

/** `POST /documents` response (API_and_Data_Models.md §3, Phase 2). No
 * filesystem path, storage key, or parsed content is ever included — see
 * backend/app/models/schemas.py::DocumentUploadResponse. */
export interface DocumentUploadResponse {
  document_id: string;
  access_token: string;
}
