// Best-effort financial-entity highlighting within an evidence excerpt
// (Frontend_Specification_v2.md §5) — see docs/PROVISIONAL_DECISIONS.md
// "P9.2" for why this is substring-matched rather than offset-based: the
// public FinancialEntity schema carries no character offset.

import type { FinancialEntity } from "@/types/clauseAnalysis";

export interface TextSegment {
  text: string;
  isEntity: boolean;
  entityType?: FinancialEntity["type"];
}

/** Splits `text` into plain/entity segments by locating each entity's
 * `raw_text` as a literal substring, first match only, longest entities
 * first (so e.g. "24 months" is claimed before a shorter unrelated "24"
 * would be). Never mutates or reorders `text` itself. */
export function highlightEntities(text: string, entities: FinancialEntity[]): TextSegment[] {
  const candidates = entities
    .filter((entity) => entity.raw_text.trim().length > 0)
    .sort((a, b) => b.raw_text.length - a.raw_text.length);

  type Match = { start: number; end: number; type: FinancialEntity["type"] };
  const claimed: Match[] = [];

  for (const entity of candidates) {
    const index = text.indexOf(entity.raw_text);
    if (index === -1) continue;
    const end = index + entity.raw_text.length;
    const overlaps = claimed.some((m) => index < m.end && end > m.start);
    if (overlaps) continue;
    claimed.push({ start: index, end, type: entity.type });
  }

  claimed.sort((a, b) => a.start - b.start);

  const segments: TextSegment[] = [];
  let cursor = 0;
  for (const match of claimed) {
    if (match.start > cursor) {
      segments.push({ text: text.slice(cursor, match.start), isEntity: false });
    }
    segments.push({ text: text.slice(match.start, match.end), isEntity: true, entityType: match.type });
    cursor = match.end;
  }
  if (cursor < text.length) {
    segments.push({ text: text.slice(cursor), isEntity: false });
  }
  return segments;
}
