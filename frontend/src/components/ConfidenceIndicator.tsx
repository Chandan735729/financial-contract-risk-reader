// Confidence indicator — Frontend_Specification_v2.md §3. Deliberately
// never uses the red/amber/green risk palette (those colors mean risk and
// nothing else) and never implies model self-reported certainty; it's a
// plain neutral-scale readout of the Risk Engine's own calibrated
// `confidence_level`/`confidence_score` (PRD_v2.md Product Principle 9).

import { ConfidenceLevel } from "@/types/enums";
import styles from "./ConfidenceIndicator.module.css";

const FILLED_DOTS: Record<ConfidenceLevel, number> = {
  [ConfidenceLevel.HIGH]: 3,
  [ConfidenceLevel.MEDIUM]: 2,
  [ConfidenceLevel.LOW]: 1,
};

const LABELS: Record<ConfidenceLevel, string> = {
  [ConfidenceLevel.HIGH]: "High",
  [ConfidenceLevel.MEDIUM]: "Medium",
  [ConfidenceLevel.LOW]: "Low",
};

export function ConfidenceIndicator({
  level,
  score,
}: {
  level: ConfidenceLevel;
  score: number;
}) {
  const filled = FILLED_DOTS[level];
  const percent = Math.round(score * 100);
  return (
    <span
      className={styles.wrapper}
      title={`Confidence score: ${percent}%. Based on measurable signals, not the model's self-reported certainty.`}
    >
      <span className={styles.label}>Confidence: {LABELS[level]}</span>
      <span className={styles.dots} aria-hidden="true">
        {[0, 1, 2].map((i) => (
          <span key={i} className={i < filled ? styles.dotFilled : styles.dotEmpty} />
        ))}
      </span>
    </span>
  );
}
