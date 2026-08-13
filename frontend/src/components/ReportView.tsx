"use client";

// Report view — Frontend_Specification_v2.md §6, Phase 9 spec §6/§14.
// Default view: HIGH/MEDIUM prominent, UNKNOWN visible but visually
// separated (its own section, not interleaved), LOW available via filter
// (unchecked by default, not simply hidden with no way back).

import { useMemo, useState } from "react";
import { RiskCategory, RiskLevel } from "@/types/enums";
import type { Clause, DocumentReport } from "@/types/clauseAnalysis";
import { SummaryBar } from "./SummaryBar";
import { FilterBar } from "./FilterBar";
import { ClauseCard } from "./ClauseCard";
import { Disclaimer } from "./Disclaimer";
import styles from "./ReportView.module.css";

const DEFAULT_LEVELS = new Set<RiskLevel>([RiskLevel.HIGH, RiskLevel.MEDIUM, RiskLevel.UNKNOWN]);

function matchesCategory(clause: Clause, category: RiskCategory | "all"): boolean {
  if (category === "all") return true;
  return clause.analysis?.risk_category === category;
}

export function ReportView({ report }: { report: DocumentReport }) {
  const [selectedLevels, setSelectedLevels] = useState<Set<RiskLevel>>(new Set(DEFAULT_LEVELS));
  const [selectedCategory, setSelectedCategory] = useState<RiskCategory | "all">("all");

  const availableCategories = useMemo(() => {
    const found = new Set<RiskCategory>();
    for (const clause of report.clauses) {
      if (clause.analysis?.risk_category) found.add(clause.analysis.risk_category);
    }
    return Array.from(found);
  }, [report.clauses]);

  const toggleLevel = (level: RiskLevel) => {
    setSelectedLevels((current) => {
      const next = new Set(current);
      if (next.has(level)) {
        next.delete(level);
      } else {
        next.add(level);
      }
      return next;
    });
  };

  const filtered = report.clauses.filter((clause) => {
    const level = clause.analysis?.risk_level;
    if (!level || !selectedLevels.has(level)) return false;
    return matchesCategory(clause, selectedCategory);
  });

  const highMedium = filtered.filter(
    (c) => c.analysis?.risk_level === RiskLevel.HIGH || c.analysis?.risk_level === RiskLevel.MEDIUM,
  );
  const unknown = filtered.filter((c) => c.analysis?.risk_level === RiskLevel.UNKNOWN);
  const low = filtered.filter((c) => c.analysis?.risk_level === RiskLevel.LOW);
  // Unaffected by the level/category filters -- there's no risk level to
  // filter by, and this case (a clause-level understanding failure) should
  // always stay visible rather than silently disappear behind a filter.
  const unanalyzed = report.clauses.filter((c) => c.analysis === null);

  return (
    <div className={styles.wrapper}>
      <SummaryBar summary={report.summary} />
      <FilterBar
        selectedLevels={selectedLevels}
        onToggleLevel={toggleLevel}
        availableCategories={availableCategories}
        selectedCategory={selectedCategory}
        onCategoryChange={setSelectedCategory}
      />

      {filtered.length === 0 && (
        <p className={styles.emptyState}>No clauses match the current filters.</p>
      )}

      {highMedium.length > 0 && (
        <section aria-labelledby="flagged-heading" className={styles.section}>
          <h2 id="flagged-heading" className={styles.sectionHeading}>
            Flagged clauses
          </h2>
          {highMedium.map((clause) => (
            <ClauseCard key={clause.clause_id} clause={clause} defaultExpanded />
          ))}
        </section>
      )}

      {unknown.length > 0 && (
        <section aria-labelledby="unknown-heading" className={styles.section}>
          <h2 id="unknown-heading" className={styles.sectionHeading}>
            Needs review
          </h2>
          <p className={styles.sectionNote}>
            These clauses didn&apos;t have enough evidence for a confident assessment.
          </p>
          {unknown.map((clause) => (
            <ClauseCard key={clause.clause_id} clause={clause} />
          ))}
        </section>
      )}

      {low.length > 0 && (
        <section aria-labelledby="low-heading" className={styles.section}>
          <h2 id="low-heading" className={styles.sectionHeading}>
            Low risk
          </h2>
          {low.map((clause) => (
            <ClauseCard key={clause.clause_id} clause={clause} />
          ))}
        </section>
      )}

      {unanalyzed.length > 0 && (
        <section aria-labelledby="unanalyzed-heading" className={styles.section}>
          <h2 id="unanalyzed-heading" className={styles.sectionHeading}>
            Not analyzed
          </h2>
          {unanalyzed.map((clause) => (
            <ClauseCard key={clause.clause_id} clause={clause} />
          ))}
        </section>
      )}

      <Disclaimer />
    </div>
  );
}
