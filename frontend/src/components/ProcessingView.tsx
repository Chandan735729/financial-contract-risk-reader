// Processing status — Phase 9 spec §5. Shows the real backend pipeline
// stages, stage-based (not a fake percentage the backend doesn't provide).

import { ProcessingStage } from "@/types/enums";
import styles from "./ProcessingView.module.css";

// Order matches the backend's ProcessingStage state machine exactly
// (backend/app/models/enums.py) — FAILED is handled separately by the
// caller, not shown in this ordered list.
const STAGE_ORDER: ProcessingStage[] = [
  ProcessingStage.QUEUED,
  ProcessingStage.PARSING,
  ProcessingStage.SEGMENTING,
  ProcessingStage.UNDERSTANDING,
  ProcessingStage.SCORING,
  ProcessingStage.GENERATING,
  ProcessingStage.VERIFYING,
  ProcessingStage.COMPLETED,
];

const STAGE_LABELS: Record<ProcessingStage, string> = {
  [ProcessingStage.QUEUED]: "Queued",
  [ProcessingStage.PARSING]: "Reading document",
  [ProcessingStage.SEGMENTING]: "Splitting into clauses",
  [ProcessingStage.UNDERSTANDING]: "Extracting terms and conditions",
  [ProcessingStage.SCORING]: "Assessing risk",
  [ProcessingStage.GENERATING]: "Writing explanations",
  [ProcessingStage.VERIFYING]: "Verifying explanations against the source text",
  [ProcessingStage.COMPLETED]: "Done",
  [ProcessingStage.FAILED]: "Failed",
};

export function ProcessingView({ stage }: { stage: ProcessingStage }) {
  const currentIndex = STAGE_ORDER.indexOf(stage);

  return (
    <div className={styles.wrapper}>
      <p role="status" className={styles.headline}>
        {STAGE_LABELS[stage]}…
      </p>
      <p className={styles.note}>
        Complex or longer documents can take a little while. This page updates automatically.
      </p>
      <ol className={styles.stageList}>
        {STAGE_ORDER.map((s, index) => {
          const status = index < currentIndex ? "done" : index === currentIndex ? "current" : "pending";
          return (
            <li key={s} className={`${styles.stage} ${styles[status] ?? ""}`}>
              <span className={styles.marker} aria-hidden="true">
                {status === "done" ? "✓" : status === "current" ? "…" : ""}
              </span>
              <span>
                {STAGE_LABELS[s]}
                {status === "current" && <span className="visually-hidden"> (in progress)</span>}
                {status === "done" && <span className="visually-hidden"> (complete)</span>}
              </span>
            </li>
          );
        })}
      </ol>
    </div>
  );
}
