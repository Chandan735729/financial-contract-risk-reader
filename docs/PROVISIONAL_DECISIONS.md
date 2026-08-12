# Provisional Decisions

This document records every decision made during implementation because a
v2 document explicitly deferred to a "v1" / "original" document that does
not exist anywhere in this repository (see `docs/IMPLEMENTATION_AUDIT.md`
§3.1 for the full list of such references), plus implementation choices
(not v1-gaps) material enough to affect later phases. Phase 0/1 decisions
are in the sections below; Phase 2, Phase 3, and Phase 4 decisions are in
their own sections near the end of this file.

Per the standing source-of-truth rule: these are the smallest reasonable,
easy-to-change decisions — not reconstructions of remembered v1 content, not
internet-sourced replacements, and not silent inventions. Each is marked
`PROVISIONAL_V2` at its point of use in code so it stays visible to anyone
reading the implementation, not just this document.

If the real v1 material is later supplied, every entry below names exactly
what would need to change.

---

## 1. `users` table (auth model)

**Location:** `backend/app/models/db_models.py::User`

**What v2 says:** `Security_and_Privacy_v2.md` §4 states auth is "unchanged
from the original Security and Access Document": no login required for core
use, unguessable per-document access tokens, an optional passwordless
magic-link login for saved history is a post-MVP feature.

**What's missing:** The original Security and Access Document — the actual
table shape (what a "user" record holds, any additional profile/session
fields) is not defined anywhere accessible.

**Provisional decision:** `users` has only `id`, `email` (nullable, unique),
and `created_at`. No password field, no session table — consistent with "no
login required for core use." The nullable/unique `email` is sized to support
the documented future magic-link flow without building it now.

**Smallest-safe rationale:** Adds nothing beyond what's needed to make
`documents.user_id` a valid optional foreign key today and not preclude the
explicitly-documented future magic-link feature.

**If v1 is supplied:** Replace this table with the real schema; add an
Alembic migration; `documents.user_id` FK target is unaffected as long as
`users.id` remains a UUID primary key.

---

## 2. `documents` table — base columns (identity, ownership, storage pointer)

**Location:** `backend/app/models/db_models.py::Document`

**What v2 says:** `API_and_Data_Models.md` §2 defines only the v2
*additions* to this table explicitly: `document_type`,
`document_type_confidence`. `Security_and_Privacy_v2.md` §2 requires original
files to live in object storage, never as bytes in the database.
§4 requires an unguessable per-document access token.

**What's missing:** The base/original column set for `documents` (what a
"document" record looked like before the v2 additions) is not defined
anywhere accessible.

**Provisional decision:** `id`, `user_id` (nullable FK, `SET NULL` on
delete), `access_token`, `original_filename`, `storage_path`, `created_at`,
`updated_at`, plus the v2-explicit `document_type` /
`document_type_confidence`. `storage_path` is a reference string only — no
file bytes ever live in this table, consistent with §2.

**Smallest-safe rationale:** Only what's required to (a) satisfy the
explicit v2 additions, (b) support the explicit access-token and
object-storage-pointer requirements from `Security_and_Privacy_v2.md`, and
(c) support cascading deletes for retention (`Security_and_Privacy_v2.md`
§3).

**If v1 is supplied:** Reconcile column names/types; the v2-required
columns (`document_type`, `document_type_confidence`, `access_token`,
`storage_path`) should be preserved or mapped onto their v1 equivalents.

---

## 3. `documents.access_token` — generation mechanism

**Location:** `backend/app/models/db_models.py::Document.access_token`

**What v2 says:** `Security_and_Privacy_v2.md` §4 requires an "unguessable
per-document access token" for no-login core use.

**What's missing:** The token's generation algorithm, length, and encoding
are not specified anywhere accessible.

**Provisional decision:** The column is a unique, indexed `VARCHAR(64)`.
Phase 0 did not yet generate tokens in application code (no upload endpoint
existed yet); tests populated it with `uuid.uuid4().hex` (32 hex chars) as a
placeholder. **Update (Phase 2):** the real generation call site now exists
— `backend/app/api/documents.py::upload_document` uses
`secrets.token_urlsafe(48)`, which produces exactly 64 URL-safe base64
characters (48 bytes → 64 chars with no padding), filling the column exactly
with a cryptographically secure value.

**Smallest-safe rationale:** Reserves enough column width for a
high-entropy token without committing to an algorithm this phase has no
endpoint to exercise yet.

**If v1 is supplied:** Adopt the specified algorithm/length; shrink or grow
the column accordingly (would require a migration).

---

## 4. `processing_jobs` table

**Location:** `backend/app/models/db_models.py::ProcessingJob`

**What v2 says:** `API_and_Data_Models.md` §2 references `processing_jobs`
as an existing table "unchanged from the original Technical Architecture
Document," used to back `GET /documents/{id}/status` (§3), whose documented
response includes `stage` and `error`.

**What's missing:** The original Technical Architecture Document's table
definition.

**Provisional decision:** `id`, `document_id` (FK, cascade delete),
`stage` (the v2 `ProcessingStage` enum), `error_code` (pre-approved code
only, never a raw message — see `Security_and_Privacy_v2.md` §6),
`started_at`, `completed_at`, `created_at`, `updated_at`.

**Smallest-safe rationale:** Exactly the fields needed to back the
documented `/status` response shape (`stage`, `error`) plus the timestamps
retention jobs will need (`Security_and_Privacy_v2.md` §3), and nothing else.

**If v1 is supplied:** Reconcile column names; `stage` should keep using the
canonical `ProcessingStage` enum regardless.

---

## 5. `corpus_patterns` table — base columns

**Location:** `backend/app/models/db_models.py::CorpusPattern`

**What v2 says:** `API_and_Data_Models.md` §2 defines only the v2
*extensions* explicitly: `taxonomy_version`, `annotator_confidence`,
`is_negative_example`. The base pattern shape is referenced as extended
"from v1."

**What's missing:** The original `corpus_patterns` table definition.

**Provisional decision:** `pattern_text`, `risk_category`,
`risk_subcategory`, `source` (nullable string), plus the v2-explicit
`taxonomy_version`, `annotator_confidence`, `is_negative_example`. The
`source` value domain (`"cuad"` / `"scraped_indian"`) is not invented — it
is taken directly from the worked example in
`Risk_Taxonomy_and_Labeling_Spec.md` §6's `matched_patterns` illustration,
so `source` is a free-text column rather than an enum until more values are
confirmed.

**Smallest-safe rationale:** Only the columns needed for
`matched_patterns` to reference a pattern's text, category, and provenance.

**If v1 is supplied:** Reconcile column set; consider promoting `source` to
an enum once its full value domain is confirmed.

---

## 6. Enum/TypeScript duplication strategy (not a v1 gap — documented per Phase 0 instructions)

**Location:** `frontend/src/types/enums.ts` header;
`backend/tests/test_enum_ts_consistency.py`

Both v2 and Phase 0 instructions require the six canonical enums
(`RiskCategory`, `RiskLevel`, `ConfidenceLevel`, `DocumentType`,
`ProcessingStage`, `ErrorCode`) to match across Python, the database, and
TypeScript, and ask for the duplication strategy to be documented if
automatic generation isn't yet justified.

**Decision:** `backend/app/models/enums.py` is the single source of truth.
`frontend/src/types/enums.ts` is a manually maintained mirror, kept honest by
`backend/tests/test_enum_ts_consistency.py`, which parses the TypeScript file
as text and asserts every Python enum value appears in it — so drift fails
CI instead of failing silently. A codegen pipeline (`openapi-typescript` or
similar) was judged not yet justified for six small enums with no live
OpenAPI schema to generate from; this is a revisit-later Phase 0 judgment
call, not a placeholder for missing v1 material.

---

## Out of scope for this document

Two things are deliberately **not** included above because they are not
v1-gap decisions:

- `clauses.start_char` / `end_char` / `page_number` — `Technical_Architecture_v2.md`
  §3 says the Segmentation Service outputs "text + position" without
  specifying the field shape. This is v2's own underspecification, not a
  reference to a missing v1 document, so it was resolved directly as the
  smallest concrete representation rather than logged here as a
  `PROVISIONAL_V2` item. It is easy to change (additive columns) if a
  different position representation is specified later.
- `taxonomy_version` default value — `Risk_Taxonomy_and_Labeling_Spec.md`
  defines `taxonomy_v1` as the current taxonomy version string. The schema
  does not hard-code this as a column default (callers must supply it
  explicitly); tests use the literal `"taxonomy_v1"` value from that spec.

---

# Phase 2 — Document Ingestion & Parsing

## P2.1 Uploaded document storage strategy (local filesystem MVP)

**Location:** `backend/app/services/storage.py`

**What v2 says:** `Security_and_Privacy_v2.md` §2: "store originals in
object storage separate from the database." `Technical_Architecture_v2.md`
§10 says deployment is otherwise "unchanged from v1" (Next.js/Vercel,
FastAPI+Postgres/Railway-Render) without naming a specific object-storage
product, and §9's scalability notes are explicit that concurrency/queueing
infrastructure is "not MVP-blocking."

**What's missing:** Which object-storage backend (S3, GCS, a managed
provider, or a local path) the "original Technical Architecture Document"
assumed for the MVP.

**Provisional decision:** Local filesystem storage under a configurable
`UPLOAD_DIR` (default `./data/uploads`, gitignored). Files are written with
a server-generated name (`{document_id}.{pdf|docx}`) via `save_document_file`
— never a client-controlled path. The function signatures
(`save_document_file` / `delete_document_file`, keyed by an opaque
`storage_path` string) intentionally mirror what an S3/GCS-backed
implementation would look like, so swapping the backend later means
replacing the two functions' bodies, not the callers.

**Smallest-safe rationale:** Satisfies "separate from the database" (the
`documents` table only ever stores a reference string, never file bytes)
without standing up cloud infrastructure this MVP phase doesn't need
(`Security_and_Privacy_v2.md` §9 "Do-Not-Over-Engineer").

**If v1 is supplied:** If the original document specifies a concrete
provider, swap `storage.py`'s two functions for that provider's SDK calls;
`storage_path` already stores an opaque reference rather than a raw
filesystem path, minimizing the blast radius of the change.

## P2.2 `documents` upload/parsing metadata columns

**Location:** `backend/app/models/db_models.py::Document` —
`file_format`, `file_size_bytes`, `page_count`

**What v2 says:** `API_and_Data_Models.md` §2 lists only `document_type` /
`document_type_confidence` as the explicit v2 additions to `documents`. It
does not mention upload-time file metadata at all.

**What's missing:** Nothing from v1 — this is not a v1-gap. The Phase 2
task explicitly requires persisting "safe metadata available from the
upload/parsing process: filename, file type, size, page count," which has
nowhere to live in the v2-documented schema.

**Decision:** Added three nullable columns to `documents`: `file_format`
(plain `VARCHAR(8)`, values `"pdf"`/`"docx"` — not a shared canonical enum,
same precedent as `FinancialEntity.entity_type`), `file_size_bytes`
(`INTEGER`), `page_count` (`INTEGER`, PDF only — DOCX has no native page
concept; see P2.4). No separate "parsing status" column was added —
`processing_jobs.stage` / `.error_code` already cover that, and duplicating
it would violate the "keep the schema minimal" instruction.

**Migration:** `98eb6e641e38_add_upload_metadata_to_documents.py`.

## P2.3 Canonical `ErrorCode` for a page/paragraph-count cap

**Location:** `backend/app/services/parsing/models.py::ParseStatus.TOO_MANY_PAGES`

**What v2 says:** `API_and_Data_Models.md` §1's `ErrorCode` enum has
`FILE_TOO_LARGE` but no dedicated "too many pages" code, even though the
Phase 2 task explicitly requires rejecting documents "exceeding configured
page limits."

**Decision:** A page/paragraph-count cap violation maps to
`ErrorCode.FILE_TOO_LARGE` — treated as a resource/size constraint, which is
what a page cap fundamentally is. No new `ErrorCode` member was invented.

**If v1 is supplied** (or a later v2 revision adds a dedicated code): change
one line — the `_FAILURE_STATUS_TO_ERROR_CODE` mapping in
`app/services/parsing/models.py`.

## P2.4 DOCX "page limit" interpreted as a paragraph/item-count cap

**Location:** `backend/app/core/config.py::Settings.max_docx_paragraphs`;
`backend/app/services/parsing/docx_parser.py`

**What v2 says:** Phase 2 task SS2 requires rejecting "files exceeding
configured page limits" without qualifying this per format.

**What's missing:** DOCX (OOXML) has no stored page count at all — pagination
is a rendering-time computation (font metrics, page size, margins), not a
structural property of the file, unlike a PDF's fixed page objects.

**Decision:** For DOCX, `max_docx_paragraphs` (default 5000) caps the total
count of body-level items (paragraphs + table cells) as the practical proxy
for "too large a document," reported through the same
`ErrorCode.FILE_TOO_LARGE` path as a PDF page-count violation (P2.3).

**If v1 is supplied:** If a literal DOCX page count is required, it would
need a rendering step (e.g. converting to PDF first) — a materially bigger
dependency this MVP phase does not take on.

## P2.5 `ProcessingJob.stage` set to `SEGMENTING` after a successful Phase 2 parse

**Location:** `backend/app/api/documents.py::upload_document`

Parsing fully completes synchronously within the upload request (Phase 2
does not run a background worker — consistent with
`Technical_Architecture_v2.md` §9's "not MVP-blocking" queueing note). Since
`ProcessingStage` represents the pipeline's current/next stage and
segmentation (Phase 3) is what comes immediately after a completed parse,
newly created jobs are stamped `SEGMENTING`, not `PARSING`. This is an
operational default, not a v1-gap — easy to change (one enum value) once
Phase 3 exists to actually consume `SEGMENTING`-stage jobs.

## P2.6 Pre-approved user-facing error messages authored fresh

**Location:** `backend/app/core/errors.py::_DEFAULT_MESSAGES`

**What v2 says:** `API_and_Data_Models.md` §4: `user_message` should be
"the exact pre-approved string from the Security & Access Document."

**What's missing:** That document (already flagged missing in the Phase
0/1 sections above). Phase 2 adds five new error codes
(`FILE_TOO_LARGE`, `UNSUPPORTED_FILE_TYPE`, `CORRUPTED_FILE`,
`PASSWORD_PROTECTED`, `LOW_TEXT_CONTENT`) that need a user-facing string.

**Decision:** Short, plain, non-alarming strings were written fresh for
each new code, consistent with the language-policy tone
(`Security_and_Privacy_v2.md` §7) even though that policy targets clause-risk
language specifically, not upload errors.

**If v1 is supplied:** Replace the five new dictionary values with the
pre-approved strings; no code structure change needed.

## P2.7 HTTP status codes per `ErrorCode` (upload path)

**Location:** `backend/app/api/documents.py::_STATUS_CODE_BY_ERROR_CODE`

v2 defines the error *body* shape (`API_and_Data_Models.md` §4) but never
specifies HTTP status codes per `ErrorCode`. Standard REST semantics were
used: `413` for `FILE_TOO_LARGE`, `415` for `UNSUPPORTED_FILE_TYPE`, `422`
for `CORRUPTED_FILE` / `PASSWORD_PROTECTED` / `LOW_TEXT_CONTENT` (all
well-formed-request-but-semantically-invalid-content cases). Not a v1-gap —
a REST-convention judgment call, isolated to one dict, trivial to change.

---

# Phase 3 — Clause Segmentation & Structure Analysis

## P3.1 `Clause.page_number` holds the clause's *starting* page only

**Location:** `backend/app/models/db_models.py::Clause.page_number`;
`backend/app/services/segmentation_service.py::segment_document`

**What v2 says:** `API_and_Data_Models.md` §2 gives `clauses` a single
`page_number INTEGER, nullable` column. `Technical_Architecture_v2.md` §3
says the Segmentation Service outputs "text + position" without specifying
whether a clause needs to carry a page *range*.

**What's missing:** Nothing from v1 — this is v2's own schema not
anticipating that a single clause can legitimately span multiple pages
(Phase 3 spec §7 explicitly requires this: "the segmentation engine must be
able to produce a single logical clause spanning pages").

**Decision:** `Clause.page_number` is set to the page of the *first*
contributing text block. No new column was added for an end page — per
Phase 3 spec §7's explicit instruction ("inspect the v2 contract first. Do
not silently invent a new public schema"), the existing single-column shape
is respected as-is rather than extended. A clause's full page span is
recoverable later (if ever needed) from its contributing text's position
relative to `documents`' parsed pages — Phase 3 does not need it, since
`page_number` here exists for citation/display purposes ("this clause is
found around page N"), not for page-range analytics.

**Smallest-safe rationale:** Zero schema change; a `null`/single-page value
degrades gracefully for every consumer that assumes one page per clause
(e.g. Frontend_Specification_v2.md's evidence display, which cites *spans*,
not whole-clause page ranges, per `Grounding_and_Evidence_Spec.md`).

**If a page-range is later required:** Add a nullable `end_page_number`
column via a new Alembic migration; `segment_document()` already computes
the last contributing block's `page_number` internally (visible on
`SegmentedClause` via its blocks) and would only need one new field wired
through `persist_clauses`.

## P3.2 `Clause.start_char`/`end_char` reference source-block offsets, not a `raw_text` slice bound

**Location:** `backend/app/services/segmentation_models.py::SegmentedClause`

**What v2 says:** Same "text + position" underspecification as P3.1 — no
document defines whether `start_char`/`end_char` must satisfy
`raw_text == source_document_text[start_char:end_char]` exactly.

**What's missing:** Nothing from v1 (v2's own gap). Exact reconstruction is
not achievable without also persisting a canonical whole-document text
string nowhere in the current schema, and Phase 2 explicitly does not
persist `ParsedDocument` text (see the Phase 2 entry below).

**Decision:** `start_char` = the first contributing `DocumentTextBlock`'s
own `start_char` (Phase 2's per-document reading-order offset numbering);
`end_char` = the last contributing block's `end_char`. `raw_text` is a
separate reconstruction (blocks joined with `"\n"`, with suppressed
headers/footers and DOCX explicit headings excluded) that does not attempt
to equal that exact character range. This is documented on
`SegmentedClause` itself and enforced as a *traceability* invariant, not an
*exact-slice* invariant, by `validate_invariants()` — see Phase 3 spec §10
("Where exact character-level reconstruction is impossible ... document the
expected invariant").

**If v1 is supplied** (or a later phase needs exact reconstruction): would
require persisting the canonical parsed document text and redefining these
offsets against it — a larger change than this phase's scope justifies.

## P3.3 Segmentation confidence is a documented heuristic, not a calibrated score

**Location:** `backend/app/services/segmentation_service.py` (`_BASE_CONFIDENCE`,
`_score_clause`, `_detect_document_anomaly`)

Phase 3 spec §8 explicitly permits this ("A documented heuristic confidence
is acceptable at this phase") and requires it be clearly distinguished from
the Risk Engine's future calibrated `confidence_score`. Not a v1-gap — an
explicit, sanctioned MVP scope boundary. The heuristic combines a base score
per boundary-detection signal (numbered/lettered/heading/fallback) with
penalties for oversized, undersized, or over-fragmented clauses, plus
document-level anomaly detection (single clause dominating the document,
many tiny fragments, non-increasing top-level numbering) that forces
`low_confidence_flag=True` across the whole document. All thresholds
(`_LARGE_CLAUSE_CHARS`, `_TINY_CLAUSE_CHARS`, `_LOW_CONFIDENCE_THRESHOLD`,
etc.) are named module constants, not tuned against a labeled benchmark —
see P3.6 below for what the current benchmark can and cannot validate.

**If/when a real annotated segmentation benchmark exists:** threshold values
and the base-confidence table are the only things that should need
adjusting; the signal-detection logic itself does not need to change.

## P3.4 Clause granularity: every numbered unit is its own clause, not grouped under its parent section

**Location:** `backend/app/services/segmentation_service.py::_assemble_groups`

**What v2 says:** Neither `Technical_Architecture_v2.md` nor
`Risk_Taxonomy_and_Labeling_Spec.md` defines what counts as one "clause" —
whether "3. Repayment" plus its "3.1"/"3.2" sub-items should be one clause
or three.

**Decision:** Every numbered unit at any level (top-level "1.", nested
"3.1"/"1.1.1", lettered "(a)", roman "(ii)") becomes its own clause. A
heading line (DOCX explicit style, or a PDF bold/short heuristic) sets
`section_heading` metadata for the clauses that follow it rather than
becoming — or merging into — a clause itself. This matches how risk
analysis in this product actually operates: a `ClauseAnalysis` record
(`Risk_Taxonomy_and_Labeling_Spec.md` §6) is meant to carry one risk
judgment, and "3.1" and "3.2" under "3. Repayment" routinely carry different
risk categories (e.g. a prepayment penalty vs. a payment schedule) — merging
them would blur two distinct risk signals into one record.

**Smallest-safe rationale:** Matches the leaf-level granularity real
contract-analysis corpora (e.g. CUAD, referenced in
`Dataset_and_Evaluation_Spec.md` §1) label at, and keeps clause boundaries
mechanically derivable from numbering alone rather than requiring a
numbering-hierarchy parser.

## P3.5 Repeated header/footer suppression is a documented heuristic

**Location:** `backend/app/services/segmentation_service.py::_detect_repeated_lines`

Phase 3 spec §5 requires suppressing "obvious" repeated headers/footers
without specifying a detection algorithm. Two independent heuristics are
used: (1) a line matching a bare page-number shape ("Page 3 of 12"), and (2)
a short (≤60 char) line whose digit-normalized text repeats on ≥3 distinct
pages. Both thresholds (`_HEADER_FOOTER_CANDIDATE_MAX_CHARS = 60`,
`_MIN_REPEAT_PAGES = 3`) are named constants chosen to avoid two known
failure modes found during development: (a) applying digit-normalization to
long lines caused unrelated sentences that merely contain different numbers
to be misidentified as a repeated footer (fixed by restricting
digit-normalized comparison to short candidate lines only); (b) requiring
repetition on only 2 pages would treat a genuinely repeated 2-page document
title as a footer. Not a v1-gap — no v2 document specifies these thresholds.

## P3.6 Segmentation evaluation is synthetic-only

**Location:** `backend/tests/fixtures/segmentation_benchmark.py`,
`corpus/eval/run_segmentation_eval.py`

`Dataset_and_Evaluation_Spec.md` §4 requires a real-world benchmark
(independently annotated real documents, messy/scanned sources,
inter-annotator agreement on a 20% sample). No such benchmark exists yet —
building one requires real (permission-cleared) source documents and human
annotation this phase does not have. The ten synthetic benchmark cases
built here are hand-authored, clean-by-construction, and useful only for
(a) proving the evaluation harness's metric computations are correct and
(b) catching future regressions in the rule engine's behavior on known
structural patterns. **The measured numbers (P=1.00, R=0.97, F1=0.98
overall on this synthetic set, see the Phase 3 completion report) are not a
production-accuracy claim** — see the explicit warning printed by
`run_segmentation_eval.py` and in `segmentation_benchmark.py`'s module
docstring. Building the real benchmark remains open work under
`Dataset_and_Evaluation_Spec.md` §4 / `Implementation_Roadmap.md` Phase 5.

## P3.7 `ProcessingStage` transition on segmentation completion

**Location:** `backend/app/services/segmentation_service.py::persist_clauses`

Extends the pattern already established in Phase 2 (`SEGMENTING` set after
a successful upload/parse): a successful `persist_clauses` call (at least
one clause produced) advances the job to `ProcessingStage.UNDERSTANDING`
(Phase 4's entry point). A `ParsedDocument` with zero usable blocks (Phase 3
spec §13 "empty/invalid parser result") advances the job to `FAILED` with
`error_code = ErrorCode.SEGMENTATION_LOW_CONFIDENCE` — the only existing
canonical code that fits. A merely *low-confidence-but-non-empty* result
does **not** fail the job (Phase 3 spec §9: "Do not fail an otherwise
readable document merely because segmentation confidence is low") — it
still advances to `UNDERSTANDING` with `low_confidence_flag=True` on its
clauses, for later phases/UI to surface honestly.

---

# Phase 4 — Clause Understanding & Hybrid Retrieval

## P4.1 Pending (unscored) `clause_analyses` row

**Location:** `backend/app/services/clause_understanding_service.py::get_or_create_pending_analysis`

**What v2 says:** `API_and_Data_Models.md` §2 makes `matched_patterns` and
`financial_entities` children of `clause_analyses` (FK on
`clause_analysis_id`), and `clause_analyses.risk_level`/`confidence_level`
are `NOT NULL`. Phase 4 spec (header): "None of these three components may
independently decide HIGH/MEDIUM/LOW/UNKNOWN. They produce evidence/signals.
The Risk Engine decides later" (Phase 5).

**What's missing:** v2 doesn't define an intermediate "signals collected,
not yet scored" persisted state — only "clause" (pre-analysis) and
"clause_analysis" (fully scored) exist as concepts.

**Decision:** Phase 4 creates (or reuses) one `clause_analyses` row per
clause in exactly the state Phase 0's own `ClauseAnalysis` Pydantic
validator already requires `UNKNOWN` + `abstained=True` to travel together:
`risk_level=UNKNOWN`, `risk_score=0.0`, `confidence_level=LOW`,
`confidence_score=0.0`, `abstained=True`, `abstain_reason="Risk Engine has
not yet scored this clause..."`, `model_version="unscored"`,
`engine_version="unscored"`. `financial_entities`/`matched_patterns`
attach to this row; `trigger`/`condition`/`consequence`/`affected_party`
are set directly on it (per Phase 4 spec §21: "Condition data should be
stored using the existing clause_analysis representation"). Phase 5 updates
this same row in place — it is not a duplicate/parallel representation, and
no new table was created (Phase 4 spec §21/§26).

**Smallest-safe rationale:** Reuses an invariant Phase 0 already enforces
(UNKNOWN requires abstained=True) rather than inventing a new status field
or relaxing the `NOT NULL` constraints, which would have weakened a
correctness guarantee `clause_analyses` consumers already rely on.

**If v1 is supplied:** Only relevant if a v1 doc defines a different
pending-row shape; the get-or-create lookup (`clause_id` → one active
analysis) and the child-table wiring would be unaffected either way.

## P4.2 `corpus_version` column on `corpus_patterns`

**Location:** `backend/app/models/db_models.py::CorpusPattern.corpus_version`

**What v2 says:** `Dataset_and_Evaluation_Spec.md` §3 requires corpus
versioning ("every labeled batch is tagged `corpus_v1`, `corpus_v1.1`...");
`AI_Risk_Engine_Design.md` §2/§7 requires every retrieval result to carry a
corpus version and "reject mixing corpus/taxonomy versions." But
`API_and_Data_Models.md` §2's `corpus_patterns` column list (extended from
v1: `taxonomy_version`, `annotator_confidence`, `is_negative_example`) never
lists a corpus_version column.

**Decision:** Added `corpus_version: VARCHAR(32) NOT NULL, default
"corpus_v1"` (migration `6e96f85aa20b`) — the smallest schema extension that
makes the explicitly-required versioning check possible, following the same
pattern as P2.2 (Phase 2's `documents` metadata columns).

**Version-mismatch enforcement mechanism:** rather than loading the whole
corpus and filtering, `_load_corpus_patterns` only ever queries rows
matching *both* the caller's requested `taxonomy_version` and
`corpus_version`; the vector store additionally uses one Chroma collection
per `(taxonomy_version, corpus_version)` pair. A pattern under a different
version is therefore never a candidate in the first place — "reject
incompatible combinations" (Phase 4 spec §7) is satisfied by construction,
not by a runtime exception. This is a documented design choice, not a
v2-specified mechanism (v2 only states the requirement, not the
implementation).

## P4.3 Document-type filtering is a hard filter on known types, no filter on `unknown`

**Location:** `backend/app/services/retrieval_service.py::is_category_applicable`,
`RISK_CATEGORY_DOCUMENT_TYPE_APPLICABILITY`

**What v2 says:** `Risk_Taxonomy_and_Labeling_Spec.md` §1 states each
subcategory's applicable `document_type` (`loan`/`insurance`/`both`).
`AI_Risk_Engine_Design.md` §3/§7 places the analogous `doc_type_relevance`
gate at the *scoring* layer, as a multiplicative (soft) weight, not a hard
retrieval-time exclusion. Phase 4 spec §5 separately asks retrieval itself
to "support metadata filtering by document type."

**Decision:** At the retrieval layer specifically, corpus patterns whose
category is inapplicable to a *known* (`loan`/`insurance`) document type
are excluded from candidacy entirely (a real, literal filter, per Phase 4
spec §5's explicit ask); `document_type=unknown` applies no filtering
at all, per that same section's explicit caution. This is a stricter,
retrieval-layer application than `AI_Risk_Engine_Design.md`'s soft
scoring-layer gate — the two are not in conflict (Phase 5's
`doc_type_relevance` gate still applies on top, over whatever categories
survive this filter), but v2 doesn't explicitly say retrieval-layer
filtering should be hard vs. soft, so this is a documented interpretation.
`RiskCategory.OTHER` (no stated `document_type` in the taxonomy — "reserved
for genuinely novel risk patterns") and patterns with no assigned category
are always treated as applicable (nothing to judge inapplicability
against), never guessed at.

**If v1 is supplied:** If a stricter/looser filtering policy is specified,
only `RISK_CATEGORY_DOCUMENT_TYPE_APPLICABILITY` and
`is_category_applicable`'s call site need to change.

## P4.4 Embedding model, top-k, and floor thresholds

**Location:** `backend/app/core/config.py`

`AI_Risk_Engine_Design.md` §2 specifies "sentence-transformers" and
"top-k=5" but not a specific model checkpoint or floor values ("a floor for
candidate consideration, not a decision threshold" — value unspecified).
Settings added: `embedding_model_name = "sentence-transformers/all-MiniLM-L6-v2"`
(small, fast, standard choice for a laptop-buildable MVP — Phase 4 spec
§8/§22), `retrieval_top_k = 5` (the one explicit v2 value),
`retrieval_min_similarity_floor = 0.3`, `retrieval_min_lexical_floor = 0.1`
(both empirically chosen during development against synthetic test
queries, not calibrated against a labeled benchmark — same "documented
heuristic, not calibrated" posture as Phase 3's segmentation confidence
thresholds). All are named, versionable settings, never hardcoded at call
sites (Phase 4 spec §4).

## P4.5 Lexical score normalization: saturating transform, not per-query min-max

**Location:** `backend/app/services/retrieval/lexical.py::_saturate`

Not specified by v2 at all — BM25 raw scores are unbounded and v2 only says
"lexical_score" without a normalization method. Min-max normalization
against each query's own candidate set was implemented first and rejected
after empirical testing: on a small corpus, whichever pattern scores
highest is pushed to exactly 1.0 *regardless of true relevance* — a
completely unrelated synthetic test query still produced a "1.0" top
lexical score purely from BM25 IDF noise on a 5-pattern corpus. Replaced
with a saturating transform `score / (score + K)`, `K=4.0` (chosen
empirically: real near-exact-text overlap produces raw BM25 scores in the
high single digits to tens; incidental token overlap on unrelated text
stays in the low single digits, which the transform keeps well below
typical floor thresholds). `K` is a documented heuristic constant, not a
calibrated value — revisit once a real labeled benchmark exists
(Dataset_and_Evaluation_Spec.md §4).

## P4.6 Financial entity type disambiguation rules (percentage vs. rate, amount vs. fee)

**Location:** `backend/app/services/entity_extraction_service.py`

Phase 4 spec §9 lists `percentage | amount | fee | rate | time_period` as
the minimum entity types but doesn't define the boundary between them.
Decision (all deterministic, regex-adjacency based, never LLM-inferred):
a percentage followed by a per-time qualifier ("per month", "p.a.",
"annually", ...) is `rate`; a bare percentage is `percentage`. A currency
amount is classified `fee` only when a fee-indicating word ("fee", "charge",
"penalty", "surcharge") appears within a narrow (30-char) window around it,
otherwise `amount`. The `fee` classification gets a lower
`extraction_confidence` (0.7 vs. 1.0) than a plain pattern match, since it
requires this extra contextual inference step (Phase 4 spec §11: extraction
confidence must be honest about what was actually a plain deterministic
match vs. an inferred one).

## P4.7 Currency and number-format support scope

**Location:** `backend/app/services/entity_extraction_service.py`

Phase 4 spec §18 explicitly permits documenting unsupported cases rather
than implementing them. Supported: `₹` / `Rs.` / `Rs` / `INR` / `$`
currency amounts, with either Indian (`1,99,999`) or Western (`199,999`) or
ungrouped (`1999.50`) digit grouping. **Not supported, by explicit
decision:** other currency symbols (`€`, `£`, ...), word-form numbers
("five hundred rupees", "ten thousand"). These simply produce no extracted
entity rather than a wrong one — consistent with "do not invent" (Phase 4
spec §9); no silent misparse.

## P4.8 Condition extraction does not create `evidence_spans` rows (unlike entities)

**Location:** `backend/app/services/condition_extraction_service.py`,
`backend/app/services/entity_extraction_service.py::persist_entities`

Phase 4 spec §14: "For entities and conditions, preserve: exact raw text,
source location/offset where practical." `financial_entities` has a
dedicated `evidence_span_id` FK explicitly designed for this — Phase 4
creates an unverified (`verified=False`) `evidence_spans` row per extracted
entity and links it. `clause_analyses.trigger/condition/consequence` have
no analogous per-field offset column in the v2 schema at all — there is
nowhere to attach an evidence span even if one were created. Decision:
condition extraction preserves exact substrings of `clause.raw_text`
within the `trigger`/`condition`/`consequence`/`affected_party` text
fields themselves (so they remain independently locatable by string search
against `raw_text`, satisfying "where practical") but does **not** create
synthetic `evidence_spans` rows for them — there's no schema field to link
them to, and inventing one would be exactly the "unsupported evidence
span" / new-table pattern Phase 4 spec §14/§21 warns against.

## P4.9 Retrieval and entity/condition evaluation are synthetic-only

**Location:** `backend/tests/fixtures/retrieval_benchmark.py`,
`backend/tests/fixtures/segmentation_benchmark.py` (Phase 3 precedent),
`corpus/eval/run_retrieval_eval.py`

Same posture as Phase 3's segmentation benchmark (P3.6):
`Dataset_and_Evaluation_Spec.md` §4's real-world benchmark (independently
annotated real documents, inter-annotator agreement) does not exist yet —
building it requires real permission-cleared source documents and human
annotation outside this phase's scope. The ten-pattern/ten-query synthetic
retrieval benchmark here is hand-authored and clean-by-construction, useful
for proving the Recall@k/MRR harness computes correctly and catching
regressions in the hybrid retrieval implementation, not for claiming
production accuracy. The measured numbers (Recall@1=0.90, Recall@3=1.00,
Recall@5=1.00, MRR=0.95 on this synthetic set — see the Phase 4 completion
report) are reported with that caveat attached everywhere they appear.
