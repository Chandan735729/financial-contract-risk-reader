// Report-level disclaimer — PRD_v2.md §8 step 5 ("Export/share with
// disclaimer" implies a disclaimer accompanies every report view, not only
// export, which is out of scope for this phase). Consistent with the
// language policy (Security_and_Privacy_v2.md §7): never implies legal
// advice or a legal conclusion.

import styles from "./Disclaimer.module.css";

export function Disclaimer() {
  return (
    <p className={styles.disclaimer}>
      This is an automated analysis to help you review this document, not legal advice. It may miss
      issues or misjudge risk. Review the original document and consult a qualified professional
      before making decisions.
    </p>
  );
}
