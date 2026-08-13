// Generic, safe error display — Phase 9 spec §17/§21/§22. Renders only
// pre-approved copy (an `ApiRequestError.userMessage`, or any other
// caller-supplied safe string); never a raw exception message, stack
// trace, or backend-internal detail.

import styles from "./ErrorPanel.module.css";

export function ErrorPanel({
  message,
  onRetry,
}: {
  message: string;
  onRetry?: () => void;
}) {
  return (
    <div className={styles.panel} role="alert">
      <p className={styles.message}>{message}</p>
      {onRetry && (
        <button type="button" className={styles.retryButton} onClick={onRetry}>
          Try again
        </button>
      )}
    </div>
  );
}
