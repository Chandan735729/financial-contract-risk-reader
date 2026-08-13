import { afterEach, describe, expect, it, vi } from "vitest";
import {
  clearDocumentToken,
  getDocumentToken,
  setDocumentToken,
  subscribeToTokenChanges,
} from "./tokenStore";

afterEach(() => {
  window.sessionStorage.clear();
});

describe("tokenStore", () => {
  it("returns null for a document with no stored token", () => {
    expect(getDocumentToken("doc-1")).toBeNull();
  });

  it("round-trips a token through sessionStorage, keyed per document", () => {
    setDocumentToken("doc-1", "token-a");
    setDocumentToken("doc-2", "token-b");
    expect(getDocumentToken("doc-1")).toBe("token-a");
    expect(getDocumentToken("doc-2")).toBe("token-b");
  });

  it("clears a stored token", () => {
    setDocumentToken("doc-1", "token-a");
    clearDocumentToken("doc-1");
    expect(getDocumentToken("doc-1")).toBeNull();
  });

  it("never writes the token anywhere but sessionStorage (not localStorage)", () => {
    setDocumentToken("doc-1", "token-a");
    expect(window.localStorage.getItem("fcrr:doc-token:doc-1")).toBeNull();
  });

  it("notifies subscribers on a same-tab write, which the native storage event does not do", () => {
    const listener = vi.fn();
    const unsubscribe = subscribeToTokenChanges(listener);
    setDocumentToken("doc-1", "token-a");
    expect(listener).toHaveBeenCalledTimes(1);
    clearDocumentToken("doc-1");
    expect(listener).toHaveBeenCalledTimes(2);
    unsubscribe();
    setDocumentToken("doc-1", "token-b");
    expect(listener).toHaveBeenCalledTimes(2);
  });
});
