// Supporting public API types — API_and_Data_Models.md §3-4.

import type { DocumentType, ErrorCode, ProcessingStage } from "./enums";

export interface DocumentStatus {
  document_id: string;
  stage: ProcessingStage;
  document_type: DocumentType;
  document_type_confidence: number | null;
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
