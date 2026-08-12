# AI Risk Engine Design

**Cross-references:** Risk_Taxonomy_and_Labeling_Spec.md (schema, taxonomy), Technical_Architecture_v2.md, Dataset_and_Evaluation_Spec.md (calibration data), Grounding_and_Evidence_Spec.md

---

## 1. Design Principle

The Risk Engine is a **deterministic, versioned scoring function** over multiple independent signals, not a single similarity threshold and not an LLM judgment call. Its output (`risk_level`, `risk_score`, `confidence_level`, `confidence_score`, `abstained`) is computed *before* any LLM call happens, so the LLM downstream has nothing to decide — only to explain.

## 2. Retrieval (Hybrid)

Two independent retrieval signals feed the engine per clause:

- **Dense retrieval:** clause embedding (sentence-transformers) vs. corpus embeddings (Chroma), top-k=5, returns `similarity_score` per match.
- **Lexical retrieval:** keyword/BM25-style match against corpus pattern text and a curated risk-term dictionary (e.g., "prepayment," "acceleration," "waive," "auto-renew"), returns `lexical_score` per match. This catches cases where wording is close to a known pattern but semantically drifts far enough that embeddings alone miss it, and vice versa — cases where phrasing is very different but the legal substance matches (lexical match on specific defined terms can catch this).

Both scores are retained separately in `matched_patterns` (see taxonomy spec §6 schema) rather than merged into one number before reaching the scoring function — this preserves information the combination step needs and makes retrieval failures diagnosable in evaluation (Dataset_and_Evaluation_Spec.md §4).

**Reranking:** not required for MVP given laptop-scale corpus size (low thousands of patterns). Documented as an upgrade path (cross-encoder rerank of top-10 dense results) if the eval harness shows Recall@1 is meaningfully lower than Recall@5, indicating the top result often isn't the best one.

**No-match handling:** if both dense and lexical retrieval return nothing above a low floor threshold (a floor for candidate consideration, not a decision threshold), retrieval contributes a "no signal" state to the combination step — this is explicitly different from contributing a "safe" signal (Product Principle 3, PRD_v2.md).

**Corpus versioning:** every `PatternMatch` carries the corpus/taxonomy version it was matched against (Risk_Taxonomy_and_Labeling_Spec.md §7); the engine rejects mixing mismatched versions in one scoring run.

## 3. Feature Extraction (Non-Retrieval Signals)

Computed independently of retrieval, per clause:

| Signal | Source | What it contributes |
|---|---|---|
| `entity_signal` | Entity Extraction Service (rule/regex-based) | Presence and magnitude of financial amounts/percentages/rates — a detected `5%` prepayment fee is a stronger signal than an amount-free mention of "prepayment" |
| `condition_signal` | Condition Extraction Service | Completeness of trigger→condition→consequence chain — a fully specified chain raises confidence, not severity directly |
| `rule_signal` | Deterministic keyword/pattern rules per subcategory (e.g., "arbitration" + "waive" co-occurrence) | A cheap, explainable, high-precision backstop independent of ML components — catches clear cases even if embeddings/lexical search underperform |
| `document_type_signal` | Document type detection | Filters/reweights which subcategories are plausible (e.g., `foreclosure` weighted near-zero relevance for an unsecured personal loan) |

None of these signals alone determines risk_level — they are combined in Section 4.

## 4. Combination & Scoring

**Step 1 — Candidate signal vector per clause:**
```
signals = {
  dense_similarity: max over matched_patterns,
  lexical_score:    max over matched_patterns,
  entity_strength:  f(entity count, entity magnitude vs. category norms),
  condition_completeness: {none, partial, full},
  rule_hit: boolean + which rule,
  doc_type_relevance: [0,1]
}
```

**Step 2 — Risk score (weighted combination, NOT a single threshold):**
```
raw_risk_score =
    w1 * dense_similarity
  + w2 * lexical_score
  + w3 * entity_strength
  + w4 * condition_completeness_score
  + w5 * rule_hit_boost
  * doc_type_relevance   # multiplicative gate, not additive
```
Weights (`w1..w5`) are **not hand-guessed and frozen** — they are initialized from domain reasoning (rule hits and entity strength weighted comparably to or above raw similarity, per Product Principle 2) and then tuned against the labeled eval set (Dataset_and_Evaluation_Spec.md §5) by checking precision/recall at each candidate weighting, not by a single global accuracy number.

**Step 3 — Risk level thresholding (banded, with a genuine "no decision" zone):**
```
if raw_risk_score >= HIGH_THRESHOLD:          risk_level = HIGH
elif raw_risk_score >= MEDIUM_THRESHOLD:       risk_level = MEDIUM
elif raw_risk_score >= LOW_THRESHOLD:          risk_level = LOW
else:                                          candidate_level = UNKNOWN  # see Section 6
```
Thresholds are tunable constants stored with the taxonomy/model version, adjusted using the eval set's precision/recall curves per category (high-risk precision is prioritized per PRD_v2.md §9).

**Step 4 — Confidence score (independent computation, not derived from risk_score directly):**
```
confidence_score = g(
    signal_agreement,       # do dense/lexical/rule/entity signals agree or conflict?
    evidence_completeness,  # how many/how strong are the evidence spans?
    condition_completeness, # same field as above, reused as a confidence input too
    retrieval_margin        # gap between top match and next-best match — a narrow margin lowers confidence even if the top score is high
)
```
Confidence is **calibrated**, not raw: the function `g()` is fit/validated against the eval set by checking that clauses the system rates "confidence 0.9" are actually correct ~90% of the time on held-out labeled data (see Dataset_and_Evaluation_Spec.md §6, calibration/reliability curves). Never uses an LLM's self-reported confidence as this value (Product Principle 9, PRD_v2.md).

## 5. Pseudocode (End-to-End for One Clause)

```python
def score_clause(clause, corpus_matches, entities, conditions, doc_type):
    dense = max((m.similarity_score for m in corpus_matches), default=0.0)
    lexical = max((m.lexical_score for m in corpus_matches), default=0.0)
    entity_strength = score_entities(entities, clause.candidate_category)
    condition_score, condition_completeness = score_conditions(conditions)
    rule_hit, rule_boost = check_rules(clause.raw_text, doc_type)
    doc_relevance = category_doc_type_relevance(clause.candidate_category, doc_type)

    raw_score = (
        W1 * dense + W2 * lexical + W3 * entity_strength +
        W4 * condition_score + W5 * rule_boost
    ) * doc_relevance

    confidence = calibrated_confidence(
        signals=[dense, lexical, entity_strength, rule_hit],
        evidence_count=len(clause.evidence_spans),
        condition_completeness=condition_completeness,
        retrieval_margin=retrieval_margin(corpus_matches)
    )

    level = threshold_to_level(raw_score)
    level, abstained, reason = apply_abstention_rules(level, confidence, clause, corpus_matches)

    return RiskResult(risk_level=level, risk_score=raw_score,
                       confidence_score=confidence, abstained=abstained,
                       abstain_reason=reason)
```

## 6. Abstention Logic

Abstention (`risk_level = UNKNOWN`) is triggered by explicit, documented conditions — never a silent fallback:

- `raw_risk_score` falls in the ambiguous band between `LOW_THRESHOLD` and `MEDIUM_THRESHOLD` **and** `confidence_score` is below `CONFIDENCE_FLOOR`.
- No retrieval match **and** no rule hit **and** no extractable financial entity for a clause whose section heading or surrounding context suggests it's substantive (not boilerplate) — this is the concrete mechanism behind Product Principle 3 ("no match ≠ safe"): the system checks whether it has any real basis for `LOW` before assigning it, rather than defaulting there.
- Segmentation confidence is low for this clause (carried over from the Segmentation Service) — an unreliable clause boundary undermines any risk judgment about it.
- Evidence Engine could not verify any candidate evidence span against `raw_text` (Grounding_and_Evidence_Spec.md §2) — a risk judgment with no verifiable evidence is not shown as a confident judgment.

`LOW` is only assigned when there is **positive evidence of low risk** — a rule/entity/retrieval signal indicating the clause is boilerplate, procedural, or explicitly non-risky (see the "negative example" pattern in Risk_Taxonomy_and_Labeling_Spec.md §4) — or when signals are weak but the clause itself is short/administrative in a way validated during annotation (e.g., definitions sections, notice-address clauses). This distinction is what prevents `LOW` from silently absorbing `UNKNOWN` cases.

## 7. Failure Modes (Engine-Level)

| Failure mode | Symptom | Mitigation |
|---|---|---|
| Weight misconfiguration | High-risk precision drops on eval set after a weight change | Every weight change is re-run against the eval harness before merge (Dataset_and_Evaluation_Spec.md) |
| Corpus/taxonomy version mismatch | Retrieval matches reference an outdated category definition | Version check at scoring time (Section 2); mismatch halts scoring for that clause with a clear internal error |
| Overconfident calibration | `confidence_score` doesn't track real accuracy (e.g., always outputs 0.9) | Reliability diagrams computed per release (Dataset_and_Evaluation_Spec.md §6); miscalibration blocks release |
| Rule/entity extractor gaps on unusual phrasing | Genuinely risky clause scores low across all signals | Tracked as a distinct error category ("corpus gap" / "extraction gap") in error analysis, not silently absorbed into "model is imperfect" — see Dataset_and_Evaluation_Spec.md §7 |
| Doc-type misdetection | Irrelevant categories scored (e.g., foreclosure signal fires on an insurance doc) | `doc_type_relevance` gate (Section 4, Step 2) suppresses irrelevant categories multiplicatively rather than relying on retrieval alone to avoid them |
