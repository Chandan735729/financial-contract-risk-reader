# Implementation Roadmap

**Cross-references:** all other v2 documents. Prioritizes accuracy and evaluation infrastructure before UI polish, per the master prompt's explicit instruction.

---

## Phase 0 — Foundation & Schemas
**Objective:** establish the canonical data model before any pipeline logic is written, so every later phase builds against a stable contract.
**Files:** repo scaffold (frontend/backend/corpus/docs), `backend/app/models/db_models.py` (full v2 schema, API_and_Data_Models.md §2), `backend/app/models/schemas.py` (Pydantic mirrors of `ClauseAnalysis`, Risk_Taxonomy_and_Labeling_Spec.md §6), Alembic migration, shared enums (API_and_Data_Models.md §1) in both backend (Python) and frontend (TypeScript).
**Dependencies:** none.
**Tests:** migration up/down, schema round-trip serialization tests.
**Acceptance criteria:** full v2 schema exists and matches the canonical `ClauseAnalysis` shape exactly across DB, Pydantic, and TypeScript.

## Phase 1 — Parsing & Segmentation
**Objective:** reliable text/layout extraction and heuristic clause segmentation, with explicit failure signaling (no silent garbage output).
**Files:** `parsing_service.py` (PDF via PyMuPDF, DOCX via python-docx, OCR-fallback detection), `segmentation_service.py` (rule-based, per Technical_Architecture_v2.md §2).
**Dependencies:** Phase 0.
**Tests:** the parsing/segmentation unit test sets from the original Feature Ticket List (TICKET-006–008), extended with the messy/scanned/table cases from Dataset_and_Evaluation_Spec.md §4.
**Acceptance criteria:** segmentation boundary F1 measured and reported (Dataset_and_Evaluation_Spec.md §5) against the annotated eval set; failure states (`password_protected`, `low_text_content`) correctly detected and distinguishable.

## Phase 2 — Clause Understanding
**Objective:** build the three parallel extractors (retrieval, entities, conditions) that feed the Risk Engine — none of which alone decides risk.
**Files:** `retrieval_service.py` (hybrid dense + lexical, AI_Risk_Engine_Design.md §2), `entity_extraction_service.py`, `condition_extraction_service.py`.
**Dependencies:** Phase 1 (needs segmented clauses); corpus build (labeled dataset + vector index — reuses/extends the original corpus tickets, updated to the v2 taxonomy and negative-example labeling from Risk_Taxonomy_and_Labeling_Spec.md §4).
**Tests:** Recall@k/MRR for retrieval; precision/recall of entity extraction against a hand-labeled sample; condition-chain completeness accuracy.
**Acceptance criteria:** each extractor independently testable and reporting its own metrics per Dataset_and_Evaluation_Spec.md §5, before being wired into scoring.

## Phase 3 — Evidence Engine & Risk Engine
**Objective:** the core differentiator — deterministic, multi-signal, versioned risk scoring with calibrated confidence and genuine abstention.
**Files:** `evidence_engine.py` (span assembly + verification, Grounding_and_Evidence_Spec.md §2), `risk_engine.py` (AI_Risk_Engine_Design.md §4–6, including the pseudocode's `score_clause` function, threshold config, and abstention logic).
**Dependencies:** Phase 2.
**Tests:** unit tests per abstention rule (AI_Risk_Engine_Design.md §6); weight/threshold changes re-run against the eval harness (Dataset_and_Evaluation_Spec.md); calibration fit and reliability-diagram validation (Dataset_and_Evaluation_Spec.md §6).
**Acceptance criteria:** high-risk precision, macro F1, and calibration ECE all measured and meeting the thresholds in Dataset_and_Evaluation_Spec.md §8 before proceeding to Phase 4 — **this phase is the release gate for the rest of the pipeline's credibility and should not be rushed to reach a demo-able UI.**

## Phase 4 — Grounded Generation & Grounding Guard
**Objective:** explain already-decided risk assessments in plain language without introducing new claims.
**Files:** `generation_service.py` (prompt design per Grounding_and_Evidence_Spec.md §4, structurally separating "facts" from "context"), `grounding_guard.py` (claim extraction + verification, Grounding_and_Evidence_Spec.md §4).
**Dependencies:** Phase 3 (needs finalized risk_level/confidence/evidence to explain).
**Tests:** the five-case regression suite from Grounding_and_Evidence_Spec.md §7 (positive control, fabricated fee, fabricated legal conclusion, partial support, near-verbatim tolerance) — all must pass before merge.
**Acceptance criteria:** grounded explanation rate near-100% by construction; fallback rate tracked; language-policy violations (Security_and_Privacy_v2.md §7) caught by the negative control test.

## Phase 5 — Evaluation Harness (Gating Infrastructure)
**Objective:** make Phases 1–4's metrics automatically re-checkable on every future change, not one-off manual measurements.
**Files:** `corpus/eval/` scripts covering every metric in Dataset_and_Evaluation_Spec.md §5, an error-analysis report generator (categorizing failures per §7), a calibration/reliability report generator.
**Dependencies:** Phases 1–4 (needs a working pipeline to evaluate) — but should be scaffolded early (stub scripts against Phase 0's schema) so it's ready the moment Phase 1 produces real output, rather than bolted on afterward.
**Tests:** the harness's own correctness — e.g., a synthetic known-answer test set confirming the metric calculations themselves are right.
**Acceptance criteria:** running the harness produces a single report covering all Dataset_and_Evaluation_Spec.md §5 metrics and §7 error categories; this becomes a required check before any pipeline-affecting change ships, per Technical_Architecture_v2.md §9.

## Phase 6 — Report UI
**Objective:** surface the four-state risk model, confidence, and evidence clearly, per Frontend_Specification_v2.md.
**Files:** extends the original Frontend Specification Document's components — `ClauseCard` (add confidence indicator, evidence block, `UNKNOWN` state per Frontend_Specification_v2.md §5), `ReportSummaryBar` (four counts), upload/processing flow (updated stage list).
**Dependencies:** Phase 4/5 (needs real API responses matching API_and_Data_Models.md §3 to build against).
**Tests:** component tests per state (`HIGH`/`MEDIUM`/`LOW`/`UNKNOWN`, explanation-unavailable fallback), accessibility checks (contrast on the new `risk-unknown` token, per Frontend_Specification_v2.md §8).
**Acceptance criteria:** UI correctly renders every state defined in API_and_Data_Models.md §3's response shape, including the fallback/abstention cases — no state renders as blank or broken.

## Phase 7 — Security & Hardening
**Objective:** apply Security_and_Privacy_v2.md end to end before any public/demo deployment.
**Files:** access-token enforcement middleware (unchanged from original Security & Access Document), logging/data-scrubbing configuration extended for v2's new fields (Section 6), rate limiting, upload validation, retention/deletion job.
**Dependencies:** Phases 0–6 (needs the full data model and pipeline to secure).
**Tests:** the original security ticket list's tests (access-token denial, no-content-in-logs audit) extended to cover the new `clause_analyses`/`evidence_spans`/`financial_entities` tables.
**Acceptance criteria:** the Phase 7 checklist mirrors and extends the original Security & Access Document's launch-readiness checklist, with new items for entity/evidence data handling and the language-policy regression test.

## Phase 8 — Should-Have / Nice-to-Have
**Objective:** everything explicitly deferred in PRD_v2.md §7 — reranking upgrade, saved history/auth, document comparison, chat-with-document (which reuses the Phase 3–4 grounding infrastructure directly), analytics instrumentation.
**Dependencies:** stable Phase 0–7 MVP.
**Acceptance criteria:** per-feature, defined in the original Feature Ticket List structure, extended with v2 schema awareness where relevant (e.g., chat-with-document must reuse the grounding guard's claim-vs-evidence check, not a simplified version).

---

## Sequencing Note

Phases 3 and 5 are the ones most tempting to under-invest in relative to Phase 6 (UI), because UI progress is what's visible in a demo. The roadmap deliberately orders evaluation infrastructure (Phase 5) before UI (Phase 6) to keep the project honest about whether the risk engine actually works before it looks like it works.
