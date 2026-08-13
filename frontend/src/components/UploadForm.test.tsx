import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

const { pushMock, uploadDocumentMock } = vi.hoisted(() => ({
  pushMock: vi.fn(),
  uploadDocumentMock: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: pushMock }),
}));

vi.mock("@/lib/apiClient", async () => {
  const actual = await vi.importActual<typeof import("@/lib/apiClient")>("@/lib/apiClient");
  return { ...actual, uploadDocument: uploadDocumentMock };
});

import { ApiRequestError } from "@/lib/apiClient";
import { getDocumentToken } from "@/lib/tokenStore";
import { UploadForm } from "./UploadForm";

afterEach(() => {
  vi.clearAllMocks();
  window.sessionStorage.clear();
});

function pdfFile(name = "contract.pdf", size = 1024): File {
  const file = new File([new Uint8Array(size)], name, { type: "application/pdf" });
  return file;
}

describe("UploadForm", () => {
  it("rejects an unsupported file type client-side, without calling the API", async () => {
    // Dropped (not picked via the native <input accept="...">), since
    // user-event's upload() correctly refuses to select a file that
    // doesn't match `accept` -- drag-and-drop is the realistic path a
    // mismatched file actually takes past this browser-level filter.
    render(<UploadForm />);
    const dropzone = screen.getByTestId("upload-dropzone");
    const badFile = new File(["hello"], "notes.txt", { type: "text/plain" });

    fireEvent.drop(dropzone, { dataTransfer: { files: [badFile] } });

    expect(await screen.findByText("Only PDF and DOCX files are supported.")).toBeInTheDocument();
    expect(uploadDocumentMock).not.toHaveBeenCalled();
  });

  it("uploads a valid file, stores the token, and redirects to the document page", async () => {
    uploadDocumentMock.mockResolvedValue({ document_id: "doc-1", access_token: "secret-token" });
    const user = userEvent.setup();
    render(<UploadForm />);

    const input = screen.getByLabelText("Choose a file", { selector: "input" });
    await user.upload(input, pdfFile());

    await waitFor(() => expect(pushMock).toHaveBeenCalledWith("/documents/doc-1"));
    expect(getDocumentToken("doc-1")).toBe("secret-token");
  });

  it("shows the API's safe user message on upload failure, not a raw error", async () => {
    uploadDocumentMock.mockRejectedValue(new ApiRequestError(422, "low_text_content", "req-1"));
    const user = userEvent.setup();
    render(<UploadForm />);

    const input = screen.getByLabelText("Choose a file", { selector: "input" });
    await user.upload(input, pdfFile());

    expect(await screen.findByText(/scanned or image-only file/i)).toBeInTheDocument();
    expect(pushMock).not.toHaveBeenCalled();
  });
});
