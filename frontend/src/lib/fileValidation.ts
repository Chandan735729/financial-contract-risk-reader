// Client-side upload validation (Phase 9 spec §2) — a fast, friendly
// first check only. The backend re-validates everything from the actual
// file bytes (content-sniffed, never trusting extension/Content-Type) and
// remains authoritative; a file that passes this check can still be
// rejected by the API, and that rejection is what the UI ultimately shows.

// Mirrors the backend's default `max_upload_size_bytes` (20 MB,
// backend/app/core/config.py) — the frontend has no endpoint to read the
// deployed limit dynamically, so this is a best-effort match, not a
// guarantee; the backend's own limit always governs.
export const MAX_UPLOAD_SIZE_BYTES = 20 * 1024 * 1024;

const ACCEPTED_EXTENSIONS = [".pdf", ".docx"];

export interface FileValidationResult {
  valid: boolean;
  message?: string;
}

export function validateUploadFile(file: File): FileValidationResult {
  const name = file.name.toLowerCase();
  const hasAcceptedExtension = ACCEPTED_EXTENSIONS.some((ext) => name.endsWith(ext));
  if (!hasAcceptedExtension) {
    return { valid: false, message: "Only PDF and DOCX files are supported." };
  }
  if (file.size === 0) {
    return { valid: false, message: "This file appears to be empty." };
  }
  if (file.size > MAX_UPLOAD_SIZE_BYTES) {
    return { valid: false, message: "This file is too large (or has too many pages) to process." };
  }
  return { valid: true };
}
