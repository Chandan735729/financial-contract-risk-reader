// Report summary — Frontend_Specification_v2.md §6, Phase 9 spec §6.
// Four counts, UNKNOWN always its own distinct tile (never merged into
// LOW).

import { RiskLevel } from "@/types/enums";
import type { RiskSummary } from "@/types/clauseAnalysis";
import styles from "./SummaryBar.module.css";

const TILES: { level: RiskLevel; label: string; key: keyof RiskSummary }[] = [
  { level: RiskLevel.HIGH, label: "High", key: "high" },
  { level: RiskLevel.MEDIUM, label: "Medium", key: "medium" },
  { level: RiskLevel.LOW, label: "Low", key: "low" },
  { level: RiskLevel.UNKNOWN, label: "Unknown", key: "unknown" },
];

const TILE_CLASS: Record<RiskLevel, string> = {
  [RiskLevel.HIGH]: styles.high ?? "",
  [RiskLevel.MEDIUM]: styles.medium ?? "",
  [RiskLevel.LOW]: styles.low ?? "",
  [RiskLevel.UNKNOWN]: styles.unknown ?? "",
};

export function SummaryBar({ summary }: { summary: RiskSummary }) {
  const total = summary.high + summary.medium + summary.low + summary.unknown;
  return (
    <section aria-labelledby="summary-heading" className={styles.wrapper}>
      <h2 id="summary-heading" className={styles.heading}>
        Summary
      </h2>
      <p className={styles.total}>{total} clauses reviewed</p>
      <ul className={styles.tiles}>
        {TILES.map((tile) => (
          <li key={tile.level} className={`${styles.tile} ${TILE_CLASS[tile.level]}`}>
            <span className={styles.count}>{summary[tile.key]}</span>
            <span className={styles.label}>{tile.label}</span>
          </li>
        ))}
      </ul>
      {summary.unknown > 0 && (
        <p className={styles.unknownNote}>
          <strong>Unknown</strong> means the system didn&apos;t find enough evidence to assess a clause
          confidently — it is not a measure of safety.
        </p>
      )}
    </section>
  );
}
