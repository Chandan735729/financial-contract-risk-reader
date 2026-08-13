"use client";

// Reads a document's access token from `tokenStore` via
// `useSyncExternalStore` rather than `useState` + `useEffect` — the
// correct React pattern for a client-only external data source (avoids a
// server/client hydration mismatch by returning `null` for the server
// snapshot, and avoids the "setState synchronously in an effect" pitfall
// entirely, since there's no effect at all).

import { useCallback, useSyncExternalStore } from "react";
import { getDocumentToken, subscribeToTokenChanges } from "@/lib/tokenStore";

function getServerSnapshot(): string | null {
  return null;
}

export function useDocumentToken(documentId: string): string | null {
  const getSnapshot = useCallback(() => getDocumentToken(documentId), [documentId]);
  return useSyncExternalStore(subscribeToTokenChanges, getSnapshot, getServerSnapshot);
}
