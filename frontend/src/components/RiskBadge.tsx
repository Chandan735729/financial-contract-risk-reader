// Risk-level badge — Frontend_Specification_v2.md §2. Color is always
// paired with a visible text label and a distinct border style/icon, so
// the signal never depends on color alone (Phase 9 spec §18).

import { RiskLevel } from "@/types/enums";
import styles from "./RiskBadge.module.css";

const LABELS: Record<RiskLevel, string> = {
  [RiskLevel.HIGH]: "High risk",
  [RiskLevel.MEDIUM]: "Medium risk",
  [RiskLevel.LOW]: "Low risk",
  [RiskLevel.UNKNOWN]: "Unknown",
};

// Never reuses the check/warning/alert icon shapes used for HIGH/MEDIUM/LOW
// (Frontend_Specification_v2.md §2) — a question mark for UNKNOWN, a
// simple glyph per level otherwise, all rendered as text so they survive
// grayscale/high-contrast rendering.
const GLYPHS: Record<RiskLevel, string> = {
  [RiskLevel.HIGH]: "▲", // solid triangle
  [RiskLevel.MEDIUM]: "▬", // bar
  [RiskLevel.LOW]: "●", // dot
  [RiskLevel.UNKNOWN]: "?",
};

const LEVEL_CLASS: Record<RiskLevel, string> = {
  [RiskLevel.HIGH]: styles.high ?? "",
  [RiskLevel.MEDIUM]: styles.medium ?? "",
  [RiskLevel.LOW]: styles.low ?? "",
  [RiskLevel.UNKNOWN]: styles.unknown ?? "",
};

export function RiskBadge({ level }: { level: RiskLevel }) {
  return (
    <span className={`${styles.badge} ${LEVEL_CLASS[level]}`}>
      <span aria-hidden="true" className={styles.glyph}>
        {GLYPHS[level]}
      </span>
      {LABELS[level]}
    </span>
  );
}
