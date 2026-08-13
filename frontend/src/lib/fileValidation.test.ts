import { describe, expect, it } from "vitest";
import { MAX_UPLOAD_SIZE_BYTES, validateUploadFile } from "./fileValidation";

function file(name: string, size: number): File {
  return new File([new Uint8Array(size)], name);
}

describe("validateUploadFile", () => {
  it("accepts a .pdf file within the size limit", () => {
    expect(validateUploadFile(file("contract.pdf", 1024))).toEqual({ valid: true });
  });

  it("accepts a .docx file, case-insensitively", () => {
    expect(validateUploadFile(file("Contract.DOCX", 1024)).valid).toBe(true);
  });

  it("rejects an unsupported extension", () => {
    const result = validateUploadFile(file("contract.txt", 1024));
    expect(result.valid).toBe(false);
    expect(result.message).toBe("Only PDF and DOCX files are supported.");
  });

  it("rejects an empty file", () => {
    const result = validateUploadFile(file("contract.pdf", 0));
    expect(result.valid).toBe(false);
  });

  it("rejects a file over the size limit", () => {
    const result = validateUploadFile(file("contract.pdf", MAX_UPLOAD_SIZE_BYTES + 1));
    expect(result.valid).toBe(false);
    expect(result.message).toMatch(/too large/i);
  });
});
