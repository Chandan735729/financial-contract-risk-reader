# Technical Architecture v2 — Financial Contract Risk Reader

**Cross-references:** PRD_v2.md, AI_Risk_Engine_Design.md, Grounding_and_Evidence_Spec.md, Risk_Taxonomy_and_Labeling_Spec.md, API_and_Data_Models.md

---

## 1. Architecture Evaluation: What Changes from a Naive RAG Pipeline

The originally proposed pipeline (parse → segment → embed → retrieve → classify → LLM explain → grounding guard) is directionally correct but under-specifies the two hardest parts: **how risk level is actually decided** (not "top retrieval match wins") and **what happens when nothing matches** (not "default green"). v2 inserts two new stages — **Clause Understanding** (structured extraction of entities/conditions, independent of retrieval) and a genuine **Risk Engine** (a scoring/combination layer, not a threshold) — between segmentation and explanation, and makes evidence and confidence explicit outputs at every stage rather than only appearing in the final report.

## 2. Pipeline (Target)

```
CONTRACT
   │
   ▼
DOCUMENT TYPE DETECTION        (loan / insurance / unknown — biases retrieval + rules)
   │
   ▼
DOCUMENT PARSING                (PyMuPDF / python-docx, + OCR fallback)
   │
   ▼
STRUCTURE ANALYSIS              (headings, numbering, layout signals)
   │
   ▼
CLAUSE SEGMENTATION             (heuristic rule-based, per clause: text + position)
   │
   ▼
CLAUSE UNDERSTANDING            (per clause, three parallel extractors)
   ├── Risk-pattern retrieval (hybrid: dense + lexical, see AI_Risk_Engine_Design.md §2)
   ├── Entity extraction (amounts, %, fees, rates, time periods — regex + rule-based, LLM-assisted only as a fallback, never sole source)
   └── Condition/consequence extraction (trigger → condition → consequence, rule + pattern based)
   │
   ▼
EVIDENCE ENGINE                 (assembles evidence spans per candidate risk signal, verifies spans exist in raw_text)
   │
   ▼
RISK ENGINE                     (combines retrieval + lexical + entities + conditions + rules → risk_score + confidence_score, see AI_Risk_Engine_Design.md)
   │
   ├──► RISK LEVEL   (HIGH / MEDIUM / LOW / UNKNOWN)
   └──► CONFIDENCE   (0.0–1.0, calibrated — independent axis)
   │
   ▼
GROUNDED LLM EXPLANATION         (explains the Risk Engine's decision + evidence; does not make new risk judgments)
   │
   ▼
GROUNDING GUARD                  (verifies explanation claims against source text + extracted entities; blocks ungrounded output)
   │
   ▼
FINAL RISK REPORT
```

**Key architectural difference from v1:** the LLM sits *after* the risk decision, not as part of making it. It receives the Risk Engine's output (category, level, confidence, evidence, extracted entities) as structured input and is instructed to explain that decision in plain language — never to independently judge risk. This is enforced by prompt design (Grounding_and_Evidence_Spec.md §4) and by the fact that `risk_level` and `confidence_score` are already finalized and persisted before the LLM call happens.

## 3. Components

| Component | Responsibility | Key contract |
|---|---|---|
| **Parsing Service** | PDF/DOCX → structured text + layout metadata; OCR fallback detection | Outputs page/position-tagged text blocks; flags `low_text_content`, `password_protected` |
| **Segmentation Service** | Text blocks → discrete clauses | Outputs `Clause[]` with `clause_index`, `raw_text`, `section_heading`, position |
| **Retrieval Service** | Hybrid dense + lexical search against labeled corpus | Outputs ranked `PatternMatch[]` with similarity + lexical scores, or empty (never forced) |
| **Entity Extraction Service** | Detects financial amounts, percentages, rates, time periods | Outputs `FinancialEntity[]` per clause, rule/regex-based with confidence per extraction |
| **Condition Extraction Service** | Detects trigger → condition → consequence structure | Outputs structured `{trigger, condition, consequence, affected_party}` or nulls if not detected |
| **Evidence Engine** | Assembles and verifies evidence spans for every candidate signal | Outputs `EvidenceSpan[]`, each verified to be a real substring of `clause.raw_text` |
| **Risk Engine** | Combines all signals into `risk_level` + `confidence_score` | See AI_Risk_Engine_Design.md — deterministic, versioned, tunable via eval set |
| **Generation Service** | Produces plain-language explanation of the Risk Engine's decision | Input includes risk_level, category, evidence, entities — never asked to invent a verdict |
| **Grounding Guard** | Verifies every claim in the generated explanation against source text/entities | Blocks and replaces ungrounded explanations with a defined fallback |
| **Evaluation Harness** | Runs the full pipeline against the benchmark and computes metrics | Gates pipeline changes; see Dataset_and_Evaluation_Spec.md |

## 4. Data Flow Summary

A single `ClauseAnalysis` record (schema in Risk_Taxonomy_and_Labeling_Spec.md §5, API shape in API_and_Data_Models.md) is the unit of truth per clause. It is built incrementally: segmentation creates the shell, retrieval/entity/condition extraction populate signal fields, the Risk Engine populates `risk_level`/`confidence_score`/`risk_score`, generation populates `explanation`, and the grounding guard populates `explanation_grounded` and possibly nulls the explanation. No stage overwrites another stage's fields — this makes every intermediate decision independently inspectable and testable, which the evaluation harness depends on.

## 5. APIs (summary — full spec in API_and_Data_Models.md)

- `POST /documents` — upload
- `GET /documents/{id}/status` — pipeline status, per-stage
- `GET /documents/{id}/report` — full `ClauseAnalysis[]` for the document
- `GET /documents/{id}/clauses/{clause_id}/evidence` — full evidence detail for one clause (used by the UI's evidence drill-down)
- Internal-only (not exposed to frontend): retrieval, entity extraction, risk engine, and generation are backend service functions called by the pipeline orchestrator, not independent HTTP endpoints.

## 6. Databases

PostgreSQL remains the system of record; the schema is extended from v1 to carry the richer `ClauseAnalysis` object (see API_and_Data_Models.md for full DDL-equivalent). Vector store (Chroma, or FAISS as a documented scaling path) holds corpus embeddings only — never per-user document embeddings persist beyond the processing session unless explicitly retained for debugging under the retention rules in Security_and_Privacy_v2.md.

## 7. Retrieval Architecture

Hybrid: dense embedding similarity (sentence-transformers) **and** lexical/keyword match (e.g., BM25 or simple TF-IDF over the corpus) run independently per clause; both scores are passed to the Risk Engine as separate signals rather than merged into one retrieval score before that point. Reranking (cross-encoder) is a documented optional upgrade if precision at top-k is insufficient on the eval set — not required for MVP given laptop-scale corpus size. Full detail in AI_Risk_Engine_Design.md §2.

## 8. Error Handling

Every stage in Section 2 has a defined failure mode that produces a `stage_failed` status on the clause or document (not a silent skip) — see Security_and_Privacy_v2.md §2 and the per-stage failure table there for user-facing messaging. Architecturally: a failure in Entity Extraction or Condition Extraction for one clause does not block the pipeline for other clauses; a failure in Parsing or Segmentation is document-level and halts the pipeline for that document with a clear status.

## 9. Scalability Notes (not MVP-blocking, documented for the interview conversation)

- Vector store: Chroma is sufficient at labeled-corpus scale (hundreds to low thousands of patterns); FAISS with an HNSW index is the documented next step if corpus size or query volume grows.
- Pipeline concurrency: background task processing is single-document-at-a-time per worker for MVP; a queue (Celery+Redis or equivalent) is the documented upgrade path for concurrent document processing.
- Evaluation harness is designed to run in CI on every pipeline-affecting change, so scaling the *team*, not just the traffic, is supported from day one.

## 10. Deployment

Unchanged from v1: Next.js frontend (Vercel), FastAPI backend + Postgres (Railway/Render), Chroma co-located with the backend or as a managed instance. No new infrastructure requirement introduced by v2 — the added rigor is in pipeline logic and data modeling, not infrastructure.
