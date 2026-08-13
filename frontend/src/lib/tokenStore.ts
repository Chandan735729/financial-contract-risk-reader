// Access-token storage (Phase 9 spec §3). The token returned by
// `POST /v1/documents` is the only credential this app has, and it must
// never appear in a URL, log, analytics event, document title, or share
// preview.
//
// Storage choice: `sessionStorage`, keyed per document ID, not
// `localStorage`. An in-memory-only store would lose the token on a page
// refresh during processing (a real, likely occurrence — processing can
// take a while and a user may reload). `sessionStorage` survives a refresh
// within the same tab but is cleared when the tab closes and is never sent
// to the server automatically (unlike a cookie) — "avoid long-term
// persistence unless required" (Phase 9 spec §3) while still tolerating
// the one interaction pattern (refresh) that actually needs to survive.
// Opening the same document in a new tab intentionally does *not* carry
// the token — `ProcessingPage` falls back to a manual-entry prompt for
// that case (the token was only ever handed to the tab that uploaded).
//
// Guarded for SSR: `sessionStorage` doesn't exist during server rendering.

const KEY_PREFIX = "fcrr:doc-token:";

function isBrowser(): boolean {
  return typeof window !== "undefined";
}

// Same-tab writes never fire the native `storage` event (it only fires in
// *other* browsing contexts, per spec) — `useDocumentToken`
// (`hooks/useDocumentToken.ts`) needs to react to this tab's own writes
// too (e.g. the manual-entry `TokenPrompt` fallback), so this module
// notifies its own listeners directly on every write, in addition to
// whatever native `storage` events arrive from other tabs.
const listeners = new Set<() => void>();

function notifyListeners(): void {
  for (const listener of listeners) listener();
}

export function subscribeToTokenChanges(listener: () => void): () => void {
  listeners.add(listener);
  if (isBrowser()) {
    window.addEventListener("storage", listener);
  }
  return () => {
    listeners.delete(listener);
    if (isBrowser()) {
      window.removeEventListener("storage", listener);
    }
  };
}

export function setDocumentToken(documentId: string, token: string): void {
  if (!isBrowser()) return;
  try {
    window.sessionStorage.setItem(KEY_PREFIX + documentId, token);
  } catch {
    // Storage can throw (private-browsing quota, disabled storage) —
    // the token still lives in the caller's in-memory state for this
    // page load, so upload -> immediate report view still works even if
    // persistence silently fails.
  } finally {
    notifyListeners();
  }
}

export function getDocumentToken(documentId: string): string | null {
  if (!isBrowser()) return null;
  try {
    return window.sessionStorage.getItem(KEY_PREFIX + documentId);
  } catch {
    return null;
  }
}

export function clearDocumentToken(documentId: string): void {
  if (!isBrowser()) return;
  try {
    window.sessionStorage.removeItem(KEY_PREFIX + documentId);
  } catch {
    // Nothing to clean up if storage isn't available.
  } finally {
    notifyListeners();
  }
}
