"use client";

// Processing + report page (Phase 9 spec §5/§6, one route per Phase
// 8/9's own information architecture — see docs/PROVISIONAL_DECISIONS.md
// "Phase 9: processing and report share one route"). Polls
// `GET /documents/{id}/status` until COMPLETED or FAILED, then renders the
// report; the access token never appears in this URL.

import { useCallback, useEffect, useRef, useState } from "react";
import { useParams } from "next/navigation";
import { ProcessingStage } from "@/types/enums";
import type { ProcessingStatus } from "@/types/api";
import type { DocumentReport } from "@/types/clauseAnalysis";
import { ApiRequestError, getDocumentReport, getDocumentStatus } from "@/lib/apiClient";
import { setDocumentToken } from "@/lib/tokenStore";
import { useDocumentToken } from "@/hooks/useDocumentToken";
import { ProcessingView } from "@/components/ProcessingView";
import { ReportView } from "@/components/ReportView";
import { ErrorPanel } from "@/components/ErrorPanel";
import { TokenPrompt } from "@/components/TokenPrompt";
import styles from "./page.module.css";

const POLL_INTERVAL_MS = 2500;
const GENERIC_ERROR_MESSAGE = "Something went wrong. Please try again.";

function messageFor(err: unknown): string {
  return err instanceof ApiRequestError ? err.userMessage : GENERIC_ERROR_MESSAGE;
}

export default function DocumentPage() {
  const params = useParams<{ id: string }>();
  const documentId = params.id;

  const token = useDocumentToken(documentId);
  const [status, setStatus] = useState<ProcessingStatus | null>(null);
  const [report, setReport] = useState<DocumentReport | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [retryTick, setRetryTick] = useState(0);
  const pollTimer = useRef<ReturnType<typeof setInterval> | null>(null);

  const handleTokenSubmit = (value: string) => {
    setDocumentToken(documentId, value);
    setError(null);
  };

  const fetchReport = useCallback(
    async (tok: string) => {
      try {
        const r = await getDocumentReport(documentId, tok);
        setReport(r);
      } catch (err) {
        setError(messageFor(err));
      }
    },
    [documentId],
  );

  useEffect(() => {
    if (!token) return undefined;
    let cancelled = false;

    const poll = async () => {
      try {
        const s = await getDocumentStatus(documentId, token);
        if (cancelled) return;
        setStatus(s);
        if (s.stage === ProcessingStage.COMPLETED) {
          if (pollTimer.current) clearInterval(pollTimer.current);
          void fetchReport(token);
        } else if (s.stage === ProcessingStage.FAILED) {
          if (pollTimer.current) clearInterval(pollTimer.current);
        }
      } catch (err) {
        if (cancelled) return;
        if (pollTimer.current) clearInterval(pollTimer.current);
        setError(messageFor(err));
      }
    };

    void poll();
    pollTimer.current = setInterval(() => void poll(), POLL_INTERVAL_MS);

    return () => {
      cancelled = true;
      if (pollTimer.current) clearInterval(pollTimer.current);
    };
  }, [documentId, token, fetchReport, retryTick]);

  const retry = () => {
    setError(null);
    setReport(null);
    setStatus(null);
    setRetryTick((tick) => tick + 1);
  };

  if (!token) {
    return (
      <main id="main-content" className={styles.main}>
        <TokenPrompt onSubmit={handleTokenSubmit} />
      </main>
    );
  }

  if (error) {
    return (
      <main id="main-content" className={styles.main}>
        <ErrorPanel message={error} onRetry={retry} />
      </main>
    );
  }

  if (report) {
    return (
      <main id="main-content" className={styles.main}>
        <ReportView report={report} />
      </main>
    );
  }

  if (status?.stage === ProcessingStage.FAILED) {
    const message = status.error?.user_message ?? "Something went wrong while processing this document.";
    return (
      <main id="main-content" className={styles.main}>
        <ErrorPanel message={message} />
      </main>
    );
  }

  return (
    <main id="main-content" className={styles.main}>
      <ProcessingView stage={status?.stage ?? ProcessingStage.QUEUED} />
    </main>
  );
}
