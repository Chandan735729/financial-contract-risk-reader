# API and Data Models

**Cross-references:** Risk_Taxonomy_and_Labeling_Spec.md §6 (canonical `ClauseAnalysis` schema), Technical_Architecture_v2.md, Security_and_Privacy_v2.md

---

## 1. Enums (Shared Across Backend, API, and Frontend)

```python
class RiskCategory(str, Enum):
    FINANCIAL_COST = "financial_cost"
    DEFAULT = "default"
    RENEWAL = "renewal"
    LOSS_OF_RIGHTS = "loss_of_rights"
    INSURANCE = "insurance"
    INTEREST_REPAYMENT = "interest_repayment"
    TERMINATION = "termination"
    OTHER = "other"

class RiskLevel(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    UNKNOWN = "UNKNOWN"

class ConfidenceLevel(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"

class DocumentType(str, Enum):
    LOAN = "loan"
    INSURANCE = "insurance"
    UNKNOWN = "unknown"

class ProcessingStage(str, Enum):
    QUEUED = "queued"
    PARSING = "parsing"
    SEGMENTING = "segmenting"
    UNDERSTANDING = "understanding"   # entity + condition extraction + retrieval
    SCORING = "scoring"                # risk engine
    GENERATING = "generating"          # LLM explanation
    VERIFYING = "verifying"            # grounding guard
    COMPLETED = "completed"
    FAILED = "failed"

class ErrorCode(str, Enum):
    FILE_TOO_LARGE = "file_too_large"
    UNSUPPORTED_FILE_TYPE = "unsupported_file_type"
    CORRUPTED_FILE = "corrupted_file"
    PASSWORD_PROTECTED = "password_protected"
    LOW_TEXT_CONTENT = "low_text_content"          # likely scanned PDF
    SEGMENTATION_LOW_CONFIDENCE = "segmentation_low_confidence"
    GENERATION_FAILED = "generation_failed"
    GROUNDING_FAILED = "grounding_failed"
    ACCESS_DENIED = "access_denied"
    RATE_LIMITED = "rate_limited"
    INTERNAL_ERROR = "internal_error"
```

## 2. Database Models (SQLAlchemy-equivalent, extends v1 schema)

Tables `users`, `processing_jobs` are unchanged from the original Technical Architecture Document. The following are new/extended:

### `documents` (extended)
Adds to v1: `document_type` (`DocumentType`), `document_type_confidence` (float).

### `clauses` (extended)
Adds to v1: `segmentation_confidence` (float), `low_confidence_flag` (boolean).

### `clause_analyses` (new — replaces v1's simpler `risk_flags` table)
| Field | Type | Notes |
|---|---|---|
| `id` | UUID, PK | |
| `clause_id` | UUID, FK → `clauses.id` | |
| `risk_category` | `RiskCategory`, nullable | |
| `risk_subcategory` | TEXT, nullable | |
| `taxonomy_version` | TEXT | e.g. `taxonomy_v1` |
| `trigger` | TEXT, nullable | |
| `condition` | TEXT, nullable | |
| `consequence` | TEXT, nullable | |
| `affected_party` | TEXT, nullable | |
| `risk_level` | `RiskLevel` | |
| `risk_score` | FLOAT | |
| `confidence_level` | `ConfidenceLevel` | |
| `confidence_score` | FLOAT | |
| `abstained` | BOOLEAN | |
| `abstain_reason` | TEXT, nullable | |
| `explanation` | TEXT, nullable | Null if grounding guard blocked it |
| `explanation_grounded` | BOOLEAN, nullable | |
| `model_version` | TEXT | Generation model + prompt version |
| `engine_version` | TEXT | Risk Engine weights/threshold version |
| `created_at` | TIMESTAMP | |

Plain-English: one row per clause's full risk analysis — the persisted form of the canonical `ClauseAnalysis` schema (Risk_Taxonomy_and_Labeling_Spec.md §6), split across this table plus the two child tables below for the array-valued fields.

### `financial_entities` (new)
| Field | Type | Notes |
|---|---|---|
| `id` | UUID, PK | |
| `clause_analysis_id` | UUID, FK → `clause_analyses.id` | |
| `entity_type` | TEXT | `percentage`, `amount`, `fee`, `rate`, `time_period` |
| `value` | TEXT | |
| `unit` | TEXT, nullable | |
| `raw_text` | TEXT | The exact source text this was extracted from |
| `evidence_span_id` | UUID, FK → `evidence_spans.id`, nullable | Links to the verifying span |

### `evidence_spans` (new)
| Field | Type | Notes |
|---|---|---|
| `id` | UUID, PK | |
| `clause_analysis_id` | UUID, FK → `clause_analyses.id` | |
| `text` | TEXT | |
| `start_char` | INTEGER | |
| `end_char` | INTEGER | |
| `page_number` | INTEGER, nullable | |
| `verified` | BOOLEAN | Result of the mechanical substring check (Grounding_and_Evidence_Spec.md §2) |

### `matched_patterns` (new)
| Field | Type | Notes |
|---|---|---|
| `id` | UUID, PK | |
| `clause_analysis_id` | UUID, FK → `clause_analyses.id` | |
| `corpus_pattern_id` | UUID, FK → `corpus_patterns.id` | |
| `similarity_score` | FLOAT | Dense retrieval score |
| `lexical_score` | FLOAT | Lexical retrieval score |

### `corpus_patterns` (extended from v1)
Adds: `taxonomy_version`, `annotator_confidence`, `is_negative_example` (boolean — supports the "confirmed absence" labeling from Risk_Taxonomy_and_Labeling_Spec.md §4).

## 3. API Endpoints

### `POST /documents`
Upload a document. See original Security & Access Document for auth/rate-limit behavior (unchanged).
**Response:** `{ document_id, access_token }`

### `GET /documents/{id}/status`
**Auth:** access token required.
**Response:**
```json
{
  "document_id": "uuid",
  "stage": "understanding",
  "document_type": "loan",
  "document_type_confidence": 0.88,
  "error": null
}
```
On failure:
```json
{ "document_id": "uuid", "stage": "failed", "error": { "code": "low_text_content", "user_message": "..." } }
```

### `GET /documents/{id}/report`
**Auth:** access token required.
**Response:**
```json
{
  "document_id": "uuid",
  "document_type": "loan",
  "summary": { "high": 3, "medium": 5, "low": 22, "unknown": 2 },
  "clauses": [
    {
      "clause_id": "uuid",
      "clause_index": 4,
      "section_heading": "4. Prepayment",
      "raw_text": "...",
      "analysis": {
        "risk_category": "financial_cost",
        "risk_subcategory": "prepayment_penalty",
        "risk_level": "HIGH",
        "risk_score": 0.81,
        "confidence_level": "HIGH",
        "confidence_score": 0.92,
        "abstained": false,
        "abstain_reason": null,
        "trigger": "...", "condition": "...", "consequence": "...",
        "financial_entities": [{"type": "percentage", "value": "2", "unit": "%", "raw_text": "2%"}],
        "evidence_spans": [{"text": "...", "start_char": 120, "end_char": 210, "page_number": 3, "verified": true}],
        "explanation": "...",
        "explanation_grounded": true
      }
    }
  ]
}
```
`analysis` may have `explanation: null, explanation_grounded: false` for the fallback state (Grounding_and_Evidence_Spec.md §5); `risk_level: "UNKNOWN"` clauses populate `abstain_reason` and typically have empty/partial `financial_entities`/evidence.

### `GET /documents/{id}/clauses/{clause_id}/evidence`
**Auth:** access token required. Returns the full evidence detail for one clause (all spans, matched patterns with scores, entities) — used by the UI's evidence drill-down (Frontend_Specification_v2.md §5).

## 4. Error Response Shape (Standard Across All Endpoints)

```json
{ "error": { "code": "access_denied", "user_message": "Report not found or you don't have access to it.", "request_id": "uuid" } }
```
`code` is always one of `ErrorCode` (Section 1); `user_message` is the exact pre-approved string from the Security & Access Document / Security_and_Privacy_v2.md; `request_id` supports internal log correlation without exposing internal detail to the client.

## 5. Versioning

- API responses include `taxonomy_version`, `model_version` (generation), and `engine_version` (risk engine) per clause analysis, so the frontend and any external consumer can detect when scoring logic has changed between two reports.
- Endpoint versioning: `/v1/documents/...` prefix reserved from the start even though only one version exists at launch, to avoid a breaking migration later.
