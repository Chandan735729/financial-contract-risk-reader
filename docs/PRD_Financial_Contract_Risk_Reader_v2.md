# PRD v2 — Financial Contract Risk Reader

**Status:** Draft v2 — supersedes v1 in intent, not in already-built assets
**Cross-references:** Technical_Architecture_v2.md, Risk_Taxonomy_and_Labeling_Spec.md, AI_Risk_Engine_Design.md, Grounding_and_Evidence_Spec.md

---

## 1. Problem

People sign financial contracts — loans, insurance, credit agreements, BNPL — without understanding the clauses that will actually cost them: prepayment penalties, default/acceleration triggers, auto-renewal, arbitration waivers, hidden fees. Generic LLM chat tools either hallucinate legal-sounding claims or over-hedge into uselessness. The gap is a tool that is **specifically engineered not to be confidently wrong** — one that separates "we detected a pattern," "we're confident about it," and "here's the exact evidence," rather than collapsing all three into one fluent paragraph.

## 2. Target Users

Same as v1: first-time borrowers, insurance buyers/renewers, students/young professionals, and the informal "can you check this for me" advisor. v2 adds no new persona — it changes what the tool is honest about, not who it's for.

## 3. Use Cases

- Upload a loan agreement before signing → get a categorized, evidence-backed list of risk clauses with financial amounts extracted where present.
- Upload an insurance renewal → identify auto-renewal terms, exclusions, and premium-change conditions.
- Re-check a clause the user doesn't understand → see the exact triggering language and the system's confidence, not just a green/red label.
- Recognize when the system genuinely doesn't know → an `UNKNOWN` clause is a valid, honest output, not a bug.

## 4. Product Principles (binding across all documents)

1. The LLM never independently decides risk. Risk level is computed by the Risk Engine (see AI_Risk_Engine_Design.md) from multiple signals; the LLM's only job downstream of that decision is to explain it in grounded language.
2. Semantic similarity is one signal among several, never a stand-in for "this is risky."
3. No retrieval match does **not** default to `LOW`/green. It defaults to a rule-and-entity check first, and to `UNKNOWN` if that check is also inconclusive.
4. Risk level and confidence are tracked and displayed as two separate values, never merged into one score.
5. Every `HIGH` or `MEDIUM` risk prediction must carry at least one evidence span pointing at source text, or it cannot be shown as that risk level.
6. Every generated explanation is checked against source text by the Grounding Guard before being shown (see Grounding_and_Evidence_Spec.md); ungrounded explanations are replaced with a fallback, never displayed as trustworthy.
7. Four possible risk outputs exist: `HIGH`, `MEDIUM`, `LOW`, `UNKNOWN` — abstention is a first-class, expected outcome, not an error state.
8. The system extracts structured financial quantities (percentages, amounts, fees, rates, time periods, triggers, conditions, consequences) wherever the text supports it, rather than only producing prose.
9. Confidence answers "how sure is the system," risk level answers "how bad would this be if true" — these can move independently (e.g., `HIGH RISK, confidence 40%` is a valid and important output).
10. The product is built and shipped against measurable evaluation numbers (precision/recall/F1, groundedness rate, calibration), not demo impressions. See Dataset_and_Evaluation_Spec.md.

## 5. What Changed from v1

| v1 assumption | v2 correction |
|---|---|
| Vector similarity threshold → risk level | Multi-signal Risk Engine; similarity is one input |
| Green = default when nothing matches | `UNKNOWN`/rule-check is the default; green requires positive evidence of low risk |
| Explanation quality = groundedness only | Groundedness is necessary but not sufficient — evidence, risk reasoning, and calibrated confidence are tracked separately and all required |
| Single risk_flags table drives everything | Structured `ClauseAnalysis` object (see Risk_Taxonomy_and_Labeling_Spec.md §5) carries risk, confidence, evidence, and entities independently |

## 6. MVP

- Single document upload (PDF/DOCX, English), loan and insurance document types.
- Full pipeline: parsing → segmentation → clause understanding (entities/conditions) → risk engine (multi-signal, not similarity-only) → grounded explanation → grounding guard → report.
- Report shows `HIGH`/`MEDIUM`/`LOW`/`UNKNOWN` counts, not just red/amber/green — `UNKNOWN` is visually and semantically distinct from `LOW`.
- Every flagged (non-`LOW`) clause shows: risk category, confidence, evidence span(s), extracted financial entities where present, and grounded explanation.
- Evaluation harness (segmentation, retrieval, classification, groundedness) running against a hand-built benchmark, gating any pipeline change before it ships — this is MVP, not a should-have, because the product's credibility depends on it. See Dataset_and_Evaluation_Spec.md.

## 7. Explicitly Not in v1

- Jurisdiction-specific legality determination (the system never says "illegal" or "invalid" — see Security_and_Privacy_v2.md §7 language policy).
- Multi-document comparison, chat-with-document, accounts/history (same as v1, deferred).
- Fine-tuned/trained models — v2 remains embeddings + retrieval + rules + prompting, laptop-buildable, no training pipeline.
- Automatic legal conclusions of any kind — the system reports "the contract appears to..." not "this clause is unenforceable."

## 8. User Flow

1. Upload → 2. Document type detection (loan/insurance/unknown) → 3. Processing (parsing → segmentation → clause understanding → risk engine → grounded explanation → grounding guard) with live status → 4. Report: summary counts across all four risk levels, filterable list, each clause showing risk level + confidence + evidence + explanation (or fallback) → 5. Export/share with disclaimer.

## 9. Success Criteria & Quality Metrics

Quality metrics are the primary success criteria for v2 — see Dataset_and_Evaluation_Spec.md for full detail and acceptance thresholds. Summary:

- **High-risk precision** (of clauses marked `HIGH`, how many a human annotator agrees are genuinely high-risk) — this is weighted above recall, because a false `HIGH` costs user trust faster than a missed one costs safety, given the tool is explicitly a first-pass triage aid, not a sole safeguard.
- **Groundedness rate** (% of shown explanations verifiably supported by cited source text) — target near-100%, since any ungrounded explanation reaching a user is a direct violation of Product Principle 6.
- **Abstention quality** — measured, not just present: `UNKNOWN` outputs should correlate with genuinely ambiguous/low-evidence cases in the benchmark, not be a dumping ground for pipeline failures.
- **Calibration** — confidence scores should track actual correctness rate on held-out data (see Dataset_and_Evaluation_Spec.md §6).

Usage metrics (activation rate, time-to-report, export rate) remain as in v1 but are secondary — a fast, well-used tool that is miscalibrated is a worse outcome than a slower, honestly-abstaining one.

## 10. Risks

- **Overconfidence risk:** if confidence calibration is skipped or faked (e.g., using raw LLM self-reported confidence per Product Principle constraint), the product's core differentiator collapses. Mitigation: confidence must be derived from measurable signals and validated against the eval set (AI_Risk_Engine_Design.md §5).
- **Corpus risk:** taxonomy and labeling quality bound everything downstream. A shallow or biased corpus produces a system that looks sophisticated but is not (Dataset_and_Evaluation_Spec.md).
- **Abstention misuse risk:** if `UNKNOWN` is overused, the product becomes useless; if underused, it becomes overconfident. Both are measured failure modes, not vibes — track abstention rate against the benchmark's known-ambiguous cases.
- **Scope creep into legal advice:** language discipline (Security_and_Privacy_v2.md §7) must be enforced in every generated string, not just the disclaimer banner.

## 11. Roadmap (summary — see Implementation_Roadmap.md for phases)

Phase 0: foundation + schemas → Phase 1: parsing/segmentation → Phase 2: clause understanding (entities/conditions) → Phase 3: retrieval + risk engine (multi-signal) → Phase 4: grounded explanation + grounding guard → Phase 5: evaluation harness gating all of the above → Phase 6: report UI → Phase 7: security/hardening → Phase 8: should-have/nice-to-have.
