"use client";

// Upload flow — Phase 9 spec §2. Client validation is a fast first check
// only ("Do not trust client-side validation alone" — Phase 9 spec §2);
// the backend re-validates from the actual file bytes and its rejection
// is what ultimately governs.

import { useCallback, useId, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { uploadDocument, ApiRequestError } from "@/lib/apiClient";
import { setDocumentToken } from "@/lib/tokenStore";
import { validateUploadFile } from "@/lib/fileValidation";
import { ErrorPanel } from "./ErrorPanel";
import styles from "./UploadForm.module.css";

export function UploadForm() {
  const router = useRouter();
  const inputId = useId();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [dragActive, setDragActive] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submitFile = useCallback(
    async (file: File) => {
      setError(null);
      const validation = validateUploadFile(file);
      if (!validation.valid) {
        setError(validation.message ?? "This file can't be uploaded.");
        return;
      }

      setUploading(true);
      try {
        const response = await uploadDocument(file);
        setDocumentToken(response.document_id, response.access_token);
        router.push(`/documents/${response.document_id}`);
      } catch (err) {
        setError(err instanceof ApiRequestError ? err.userMessage : "Something went wrong. Please try again.");
        setUploading(false);
      }
    },
    [router],
  );

  const handleDrop = (event: React.DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    setDragActive(false);
    const file = event.dataTransfer.files[0];
    if (file) void submitFile(file);
  };

  const handleInputChange = (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (file) void submitFile(file);
  };

  return (
    <div className={styles.wrapper}>
      <div
        data-testid="upload-dropzone"
        className={`${styles.dropzone} ${dragActive ? styles.dropzoneActive : ""}`}
        onDragOver={(event) => {
          event.preventDefault();
          setDragActive(true);
        }}
        onDragLeave={() => setDragActive(false)}
        onDrop={handleDrop}
      >
        <p className={styles.instructions}>Drag and drop a PDF or DOCX contract here</p>
        <p className={styles.or}>or</p>
        <label htmlFor={inputId} className={styles.chooseButton}>
          Choose a file
        </label>
        <input
          ref={fileInputRef}
          id={inputId}
          type="file"
          accept=".pdf,.docx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
          className="visually-hidden"
          onChange={handleInputChange}
          disabled={uploading}
        />
        {uploading && (
          <p role="status" className={styles.status}>
            Uploading…
          </p>
        )}
      </div>

      {error && (
        <div className={styles.errorWrapper}>
          <ErrorPanel message={error} />
        </div>
      )}
    </div>
  );
}
