# Provisional Decisions

This document records every decision made during implementation because a
v2 document explicitly deferred to a "v1" / "original" document that does
not exist anywhere in this repository (see `docs/IMPLEMENTATION_AUDIT.md`
§3.1 for the full list of such references), plus implementation choices
(not v1-gaps) material enough to affect later phases. Phase 0/1 decisions
are in the sections below; Phase 2 decisions are in their own section near
the end of this file.

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
