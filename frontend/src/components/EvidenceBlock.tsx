// Evidence block — Frontend_Specification_v2.md §5: "the evidence and
// structured data are the trustworthy core." Financial entities are
// highlighted as facts (signal-blue), never a risk color — extracting a
// number is not itself a risk judgment.

import type { EvidenceSpan, FinancialEntity } from "@/types/clauseAnalysis";
import { highlightEntities } from "@/lib/highlightEntities";
import styles from "./EvidenceBlock.module.css";

function HighlightedExcerpt({ text, entities }: { text: string; entities: FinancialEntity[] }) {
  const segments = highlightEntities(text, entities);
  return (
    <>
      {segments.map((segment, i) =>
        segment.isEntity ? (
          <mark key={i} className={styles.entity}>
            {segment.text}
          </mark>
        ) : (
          <span key={i}>{segment.text}</span>
        ),
      )}
    </>
  );
}

export function EvidenceBlock({
  spans,
  entities,
}: {
  spans: EvidenceSpan[];
  entities: FinancialEntity[];
}) {
  const verifiedSpans = spans.filter((span) => span.verified);

  return (
    <div className={styles.wrapper}>
      <h4 className={styles.heading}>Evidence</h4>
      {verifiedSpans.length === 0 ? (
        <p className={styles.empty}>No source excerpt is available for this clause.</p>
      ) : (
        <ul className={styles.list}>
          {verifiedSpans.map((span, i) => (
            <li key={i} className={styles.excerpt}>
              <q>
                <HighlightedExcerpt text={span.text} entities={entities} />
              </q>
              {span.page_number !== null && (
                <span className={styles.pageNumber}> (page {span.page_number})</span>
              )}
            </li>
          ))}
        </ul>
      )}
      {entities.length > 0 && (
        <dl className={styles.entityList} aria-label="Extracted financial details">
          {entities.map((entity, i) => (
            <div key={i} className={styles.entityRow}>
              <dt className={styles.entityType}>{entityTypeLabel(entity.type)}</dt>
              <dd>{entity.raw_text}</dd>
            </div>
          ))}
        </dl>
      )}
    </div>
  );
}

function entityTypeLabel(type: FinancialEntity["type"]): string {
  switch (type) {
    case "percentage":
      return "Percentage";
    case "amount":
      return "Amount";
    case "fee":
      return "Fee";
    case "rate":
      return "Rate";
    case "time_period":
      return "Time period";
    default:
      return type;
  }
}
