// Public API types for clause analysis — API_and_Data_Models.md §3.
//
// This mirrors the *public* `/report` response shape, not the full internal
// canonical `ClauseAnalysis` (backend/app/models/schemas.py, which follows
// Risk_Taxonomy_and_Labeling_Spec.md §6 exactly). One field is intentionally
// omitted here for security/product reasons:
//
//   - `matched_patterns` (corpus_pattern_id, similarity_score, lexical_score
//     per retrieval match): Technical_Architecture_v2.md §5 marks retrieval
//     as "Internal-only (not exposed to frontend)", and the §3 `/report`
//     response example does not include it on the analysis object — only
//     the separate `GET /documents/{id}/clauses/{clause_id}/evidence`
//     drill-down endpoint returns matched patterns (see
//     `ClauseEvidenceDetail` below). Keeping raw corpus similarity scores
//     out of the main report payload avoids exposing retrieval/corpus
//     internals in every clause of every report by default.
//
// Do not add a second, differently-shaped interpretation of ClauseAnalysis
// here — if the backend's canonical shape changes, this file and
// `enums.ts` must be updated together (see enums.ts header for the
// duplication/consistency strategy).

import type {
  ConfidenceLevel,
  DocumentType,
  RiskCategory,
  RiskLevel,
} from "./enums";

export interface FinancialEntity {
  type: "percentage" | "amount" | "fee" | "rate" | "time_period";
  value: string;
  unit: string | null;
  raw_text: string;
}

export interface EvidenceSpan {
  text: string;
  start_char: number;
  end_char: number;
  page_number: number | null;
  verified: boolean;
}

export interface MatchedPattern {
  corpus_pattern_id: string;
  similarity_score: number;
  lexical_score: number;
}

/** The `analysis` object inside each clause of a `/report` response. */
export interface ClauseAnalysis {
  risk_category: RiskCategory | null;
  risk_subcategory: string | null;
  taxonomy_version: string;

  trigger: string | null;
  condition: string | null;
  consequence: string | null;
  affected_party: string | null;

  // risk_level and confidence are always separate fields — never merge
  // these into one value (PRD_v2.md §4, Product Principle 4).
  risk_level: RiskLevel;
  risk_score: number;
  confidence_level: ConfidenceLevel;
  confidence_score: number;

  abstained: boolean;
  abstain_reason: string | null;

  financial_entities: FinancialEntity[];
  evidence_spans: EvidenceSpan[];

  explanation: string | null;
  explanation_grounded: boolean | null;

  model_version: string;
  engine_version: string;
}

export interface Clause {
  clause_id: string;
  clause_index: number;
  section_heading: string | null;
  raw_text: string;
  // null only for the rare partial-failure case where clause understanding
  // never produced a clause_analyses row at all (Phase 8 clause-level
  // failure isolation) — distinct from a normal UNKNOWN/abstained analysis,
  // which is always present with abstain_reason set.
  analysis: ClauseAnalysis | null;
}

export interface RiskSummary {
  high: number;
  medium: number;
  low: number;
  unknown: number;
}

export interface DocumentReport {
  document_id: string;
  document_type: DocumentType;
  summary: RiskSummary;
  clauses: Clause[];
}

/** Response of GET /documents/{id}/clauses/{clause_id}/evidence — includes
 * matched_patterns, deliberately omitted from ClauseAnalysis above. */
export interface ClauseEvidenceDetail {
  clause_id: string;
  evidence_spans: EvidenceSpan[];
  financial_entities: FinancialEntity[];
  matched_patterns: MatchedPattern[];
}
