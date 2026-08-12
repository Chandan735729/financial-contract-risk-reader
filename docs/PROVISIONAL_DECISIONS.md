# Provisional Decisions — Phase 0

This document records every decision made during Phase 0 implementation
because a v2 document explicitly deferred to a "v1" / "original" document
that does not exist anywhere in this repository (see
`docs/IMPLEMENTATION_AUDIT.md` §3.1 for the full list of such references).

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
Phase 0 does not yet generate tokens in application code (no
document-creation endpoint exists yet); tests populate it with
`uuid.uuid4().hex` (32 hex chars) as a placeholder value that fits the
column. The actual generation call site (when the upload endpoint is built)
should use a cryptographically secure random source sized for the full
64-character column (e.g. `secrets.token_urlsafe`), not UUID hex.

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
