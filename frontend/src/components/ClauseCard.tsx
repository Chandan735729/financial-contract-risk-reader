"use client";

// Clause card — Frontend_Specification_v2.md §5, Phase 9 spec §8/§9/§12/§13/§15.
// Collapsed by default (§15: "do not overload the initial collapsed view");
// expanding reveals explanation/evidence/entities/confidence detail/
// abstention reason.

import { useId, useState } from "react";
import { RiskLevel } from "@/types/enums";
import type { Clause } from "@/types/clauseAnalysis";
import { RiskBadge } from "./RiskBadge";
import { ConfidenceIndicator } from "./ConfidenceIndicator";
import { EvidenceBlock } from "./EvidenceBlock";
import { formatCategory, formatSubcategory } from "@/lib/formatCategory";
import styles from "./ClauseCard.module.css";

// Grounding_and_Evidence_Spec.md §5's exact approved fallback sentence —
// never paraphrased or replaced with a frontend-invented explanation
// (Phase 9 spec §12).
function groundingFallbackMessage(level: RiskLevel, category: string | null): string {
  const categoryPhrase = category ? `${category.toLowerCase()} ` : "";
  return `We identified this as a ${level} ${categoryPhrase}concern based on the evidence below, but couldn't generate a verified plain-language explanation. Please review the original text.`;
}

const GENERATION_SKIPPED_MESSAGE =
  "A plain-language explanation wasn't generated for this clause. The risk assessment and evidence below are still accurate.";

const UNKNOWN_LEAD_IN = "We couldn't find enough evidence to assess this clause confidently.";

export function ClauseCard({ clause, defaultExpanded = false }: { clause: Clause; defaultExpanded?: boolean }) {
  const [expanded, setExpanded] = useState(defaultExpanded);
  const contentId = useId();
  const analysis = clause.analysis;

  const title = clause.section_heading ?? `Clause ${clause.clause_index + 1}`;

  if (!analysis) {
    // Clause-level understanding failure (Phase 8): no analysis row exists
    // at all — distinct from a normal UNKNOWN, which always has an
    // abstain_reason (Phase 9 objective: "faithfully represent the
    // backend's current state," not paper over a partial failure).
    return (
      <article className={`${styles.card} ${styles.unavailable}`}>
        <h3 className={styles.title}>{title}</h3>
        <p className={styles.unavailableText}>
          This clause couldn&apos;t be analyzed. The rest of the report is unaffected.
        </p>
      </article>
    );
  }

  const category = formatCategory(analysis.risk_category);
  const subcategory = formatSubcategory(analysis.risk_subcategory);
  const isUnknown = analysis.risk_level === RiskLevel.UNKNOWN;
  const isEligibleForGeneration =
    analysis.risk_level === RiskLevel.HIGH || analysis.risk_level === RiskLevel.MEDIUM;

  let explanationNode: React.ReactNode = null;
  if (analysis.explanation && analysis.explanation_grounded) {
    explanationNode = <p className={styles.explanation}>{analysis.explanation}</p>;
  } else if (isEligibleForGeneration && analysis.explanation_grounded === false) {
    explanationNode = (
      <p className={styles.fallback}>{groundingFallbackMessage(analysis.risk_level, category)}</p>
    );
  } else if (isEligibleForGeneration && analysis.explanation_grounded === null) {
    explanationNode = <p className={styles.fallback}>{GENERATION_SKIPPED_MESSAGE}</p>;
  }

  return (
    <article className={`${styles.card} ${isUnknown ? styles.unknownCard : ""}`}>
      <h3 className={styles.title}>
        {title}
        {subcategory && <span className={styles.subcategory}> &middot; {subcategory}</span>}
      </h3>

      <button
        type="button"
        className={styles.header}
        aria-expanded={expanded}
        aria-controls={contentId}
        onClick={() => setExpanded((value) => !value)}
      >
        <span className={styles.headerLeft}>
          <RiskBadge level={analysis.risk_level} />
          {category && <span className={styles.category}>{category}</span>}
        </span>
        <span className={styles.headerRight}>
          <ConfidenceIndicator level={analysis.confidence_level} score={analysis.confidence_score} />
          <span className={styles.chevron} aria-hidden="true">
            {expanded ? "−" : "+"}
          </span>
          <span className="visually-hidden">{expanded ? "Hide details" : "Show details"}</span>
        </span>
      </button>

      {isUnknown && !expanded && <p className={styles.unknownLeadIn}>{UNKNOWN_LEAD_IN}</p>}

      {expanded && (
        <div id={contentId} className={styles.content}>
          {isUnknown && (
            <div className={styles.abstainBox}>
              <p className={styles.unknownLeadIn}>{UNKNOWN_LEAD_IN}</p>
              {analysis.abstain_reason && <p className={styles.abstainReason}>{analysis.abstain_reason}</p>}
            </div>
          )}

          {explanationNode}

          <EvidenceBlock spans={analysis.evidence_spans} entities={analysis.financial_entities} />

          <details className={styles.sourceText}>
            <summary>Read the original clause text</summary>
            <p>{clause.raw_text}</p>
          </details>
        </div>
      )}
    </article>
  );
}
