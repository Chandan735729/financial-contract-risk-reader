"use client";

// Fallback when a document's access token isn't in sessionStorage for this
// tab (opened the report link in a new tab/window, or storage was
// cleared) — Phase 9 spec §3 note on avoiding long-term persistence still
// means the common "refresh this tab" case works via tokenStore, but this
// covers the rest without ever putting the token in the URL.

import { useState } from "react";
import styles from "./TokenPrompt.module.css";

export function TokenPrompt({ onSubmit }: { onSubmit: (token: string) => void }) {
  const [value, setValue] = useState("");

  return (
    <form
      className={styles.form}
      onSubmit={(event) => {
        event.preventDefault();
        const trimmed = value.trim();
        if (trimmed) onSubmit(trimmed);
      }}
    >
      <label htmlFor="access-token-input" className={styles.label}>
        Enter your access token to view this report
      </label>
      <p className={styles.hint}>
        This was shown once when you uploaded the document. It isn&apos;t saved anywhere except this
        browser tab.
      </p>
      <input
        id="access-token-input"
        type="password"
        autoComplete="off"
        value={value}
        onChange={(event) => setValue(event.target.value)}
        className={styles.input}
      />
      <button type="submit" className={styles.submitButton}>
        Continue
      </button>
    </form>
  );
}
