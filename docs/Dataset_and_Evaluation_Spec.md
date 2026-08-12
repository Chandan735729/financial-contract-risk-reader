# Dataset and Evaluation Spec

**Cross-references:** Risk_Taxonomy_and_Labeling_Spec.md, AI_Risk_Engine_Design.md, Grounding_and_Evidence_Spec.md

---

## 1. Corpus Strategy

A large scraped corpus is not automatically better than a smaller, well-labeled one — labeling quality and category coverage matter more than raw volume for a system whose core promise is precision on high-risk predictions. The corpus combines:

- **CUAD subset:** limited to categories that map cleanly onto the taxonomy (Risk_Taxonomy_and_Labeling_Spec.md §1) — primarily useful for `loss_of_rights` (arbitration, waiver, limitation of remedies) and some `termination`/`renewal` patterns, since CUAD is commercial-contract data, not consumer lending/insurance. **Explicit limitation:** CUAD does not cover consumer loan prepayment penalties, foreclosure/default triggers in retail lending, or Indian insurance exclusion language well — these categories rely primarily on the scraped corpus, and this should not be papered over.
- **Scraped Indian loan/insurance T&Cs:** the primary source for `financial_cost`, `default`, `renewal`, and `insurance` categories, collected only from sources with confirmed permission (Technical Architecture v2 / prior Feature_Ticket_List TICKET-010 process applies unchanged).
- **Synthetic/paraphrased augmentation (optional, should-have):** once a base labeled set exists, generate paraphrased variants of known patterns (different wording, same substance) to improve lexical/semantic robustness — must be reviewed by an annotator before inclusion, never auto-accepted.

## 2. Labeling Schema & Annotation Guidelines

Full field-level schema is in Risk_Taxonomy_and_Labeling_Spec.md §6. Process:

1. Annotator reads clause in context (not in isolation — surrounding clauses provided) to avoid mislabeling due to missing context.
2. Assigns `risk_category`/`risk_subcategory`/`severity`/`confidence` per Risk_Taxonomy_and_Labeling_Spec.md §2–3.
3. Marks exact `evidence_span` (copy-verifiable substring, not paraphrase).
4. Explicitly labels **negative examples** (clauses that raise a topic but confirm no risk — Risk_Taxonomy_and_Labeling_Spec.md §4) — required, not optional, since these train the "no match ≠ safe, but also not everything is risky" distinction the Risk Engine depends on.
5. Flags genuinely ambiguous cases with a note rather than forcing a confident label — these become part of the `UNKNOWN`/abstention benchmark (Section 4.4).

## 3. Quality Control

- **Inter-annotator agreement:** 15–20% of the corpus double-labeled; Cohen's kappa computed per category. Categories below an agreed threshold (e.g., κ < 0.6) are flagged for definition clarification in the taxonomy before being trusted as training signal for rule/threshold tuning.
- **Spot audits:** a founder/lead review pass on a random sample each labeling batch, checking for annotator drift.
- **Train/dev/test separation:** split at the **document** level, not clause level — clauses from the same source document must not appear across splits, to prevent leakage (a model "learning" a specific document's phrasing rather than generalizing). Target split: 70/15/15.
- **Corpus versioning:** every labeled batch is tagged (`corpus_v1`, `corpus_v1.1`, …) with a changelog; the vector index (Technical_Architecture_v2.md) and `taxonomy_version` compatibility are both recorded per corpus version.

## 4. Real-World Benchmark Design

A held-out benchmark, separate from the training/dev labeled corpus, built specifically to stress-test the pipeline:

| Category | Included cases |
|---|---|
| Document quality | clean digital PDFs, messy/inconsistently formatted PDFs, scanned PDFs (OCR path), DOCX with tables |
| Document length | short (2–5 pages), typical (10–20 pages), long (40+ pages) |
| Document type | loan agreements, insurance policies, consumer finance T&Cs |
| Clause difficulty | subtle risk (real but non-obvious), looks-risky-but-safe (negative examples, Section 2.4), genuinely ambiguous language |
| Structural difficulty | numbered/lettered clauses, unstructured prose, mixed formatting, cross-referencing clauses |

**Annotation process for the benchmark:** each document is independently labeled end-to-end (every clause gets a ground-truth `ClauseAnalysis` per Risk_Taxonomy_and_Labeling_Spec.md §6) by at least one trained annotator, with a second annotator resolving a random 20% sample for agreement checking — same process as Section 3, applied at benchmark-construction time so the benchmark itself is trustworthy.

## 5. Metrics

### Document Parsing
- Extraction accuracy (character/word-level agreement against a manually transcribed reference on a sample)
- OCR failure rate (% of scanned documents where extraction falls below a usable-text threshold)

### Segmentation
- Boundary precision, boundary recall, F1 (predicted clause boundaries vs. annotated ground truth)

### Retrieval
- Recall@1, Recall@3, Recall@5 (does the correct corpus pattern appear in top-k for a known-positive clause)
- MRR (mean reciprocal rank)

### Classification (Risk Engine output)
- Precision, recall, F1 — overall and **per category** (Risk_Taxonomy_and_Labeling_Spec.md §1 categories)
- Macro F1 (equal weight per category, so rare-but-important categories like `foreclosure` aren't swamped by common ones)
- **High-risk precision and recall specifically reported and tracked separately** — precision prioritized per PRD_v2.md §9, but recall tracked to catch systematic under-flagging
- False-positive rate, false-negative rate, both overall and per category

### Evidence
- Evidence precision (of shown evidence spans, how many are genuinely supportive of the claim, per human review)
- Evidence recall (of clauses with genuine supporting text available, how often is it surfaced)
- Citation correctness (does the cited span exist verbatim/near-verbatim in `raw_text` — mechanically checkable, see Grounding_and_Evidence_Spec.md §3)

### Grounding
- Grounded explanation rate (% of shown explanations that pass the grounding guard)
- Unsupported claim rate (% of explanation claims, on manual review, not traceable to evidence — measured on a sample even for guard-passed explanations, since the guard is a heuristic, not a proof)

### Confidence / Calibration
- Reliability diagrams: bucket predictions by `confidence_score`, compare to actual accuracy in each bucket
- Expected Calibration Error (ECE)
- Abstention quality: precision/recall of `UNKNOWN` against the benchmark's deliberately-ambiguous cases (Section 4) — is the system abstaining on genuinely hard cases, not on easy ones it's just under-confident about, and not skipping abstention on cases it should be unsure about

## 6. Calibration Method

Confidence calibration (AI_Risk_Engine_Design.md §4) is fit using the dev split: bucket the raw `confidence_score` output into deciles, compute empirical accuracy per decile on labeled dev data, and fit a monotonic calibration mapping (e.g., isotonic regression) from raw score to calibrated score. Re-validate on the held-out test split and the real-world benchmark (Section 4) before shipping any change to the confidence function. A miscalibrated confidence function (ECE above an agreed threshold) blocks release — this is treated as seriously as a classification accuracy regression.

## 7. Error Analysis Framework

Every pipeline failure or misclassification, found either in eval runs or manual review, is categorized into exactly one of:

- `parsing_failure` — text extraction itself failed or was corrupted
- `segmentation_failure` — clause boundary wrong, merging/splitting error
- `retrieval_failure` — correct pattern existed in corpus but wasn't retrieved
- `corpus_gap` — no correct pattern existed in corpus for this genuine risk type
- `semantic_similarity_error` — dense retrieval matched on surface similarity without substantive relevance
- `classification_error` — correct signals present but Risk Engine combination produced wrong level
- `severity_error` — correct category, wrong severity band
- `evidence_extraction_error` — evidence span missing, wrong, or unverifiable
- `grounding_failure` — explanation contained unsupported claims despite passing/failing the guard
- `confidence_calibration_failure` — confidence score did not reflect actual reliability

Each release's error analysis reports the **distribution** across these categories, not just an aggregate accuracy number — this is what tells you whether to invest next in corpus expansion (`corpus_gap`), engine tuning (`classification_error`), or grounding logic (`grounding_failure`), rather than guessing.

## 8. Acceptance Thresholds (Gating Release)

These are starting targets, to be revisited once real benchmark numbers exist — but the categories below must exist and be tracked, even before final numbers are set:

| Metric | Minimum bar to ship MVP |
|---|---|
| High-risk precision | Must exceed a explicitly agreed floor (e.g., ≥0.85) before any `HIGH` label is trusted in the UI without a visible confidence caveat |
| Grounded explanation rate | Near-100% by construction (ungrounded explanations are blocked, not just measured) — this metric instead tracks how *often* the fallback is triggered, which should trend down as generation prompts improve |
| Segmentation boundary F1 | Tracked and reported; a hard floor is less important than a documented trend, since messy real-world documents are the whole point of the project |
| Calibration (ECE) | Below an agreed threshold on both dev and real-world benchmark splits |
| Abstention precision on known-ambiguous benchmark cases | System should abstain on a majority of the benchmark's deliberately-ambiguous set — a system that confidently classifies everything is failing this metric even with good accuracy elsewhere |
