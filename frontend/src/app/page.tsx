// Landing/upload page (Phase 9 spec §1/§2). Replaces the Phase 0
// placeholder shell.

import { UploadForm } from "@/components/UploadForm";
import styles from "./page.module.css";

export default function HomePage() {
  return (
    <main id="main-content" className={styles.main}>
      <div className={styles.intro}>
        <h1>Financial Contract Risk Reader</h1>
        <p className={styles.subtitle}>
          Upload a loan agreement or insurance policy. We&apos;ll go through it clause by clause and
          show you what to pay attention to, with the evidence for each finding.
        </p>
      </div>
      <UploadForm />
    </main>
  );
}
