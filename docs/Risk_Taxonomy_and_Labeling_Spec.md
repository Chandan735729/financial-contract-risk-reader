# Risk Taxonomy and Labeling Spec

**Taxonomy version:** `taxonomy_v1` (all downstream schemas reference this version string)
**Cross-references:** AI_Risk_Engine_Design.md, Dataset_and_Evaluation_Spec.md, API_and_Data_Models.md

---

## 1. Hierarchical Taxonomy

Each subcategory below carries a **default severity band** (a starting point the Risk Engine adjusts using entities/conditions — not a fixed final answer) and applies to `document_type: loan | insurance | both`.

### 1.1 FINANCIAL_COST (`document_type: both`)
| Subcategory | Default severity | Definition |
|---|---|---|
| `prepayment_penalty` | HIGH-leaning | Fee/penalty charged for paying off a loan early |
| `late_payment_fee` | MEDIUM-leaning | Fee charged for a missed/late payment |
| `processing_fee` | LOW–MEDIUM | Upfront or recurring administrative fee |
| `hidden_charge` | HIGH-leaning | Fee not clearly disclosed in the main terms, discovered in fine print |
| `interest_adjustment` | MEDIUM–HIGH | Conditions under which interest rate can change |
| `renewal_price_increase` | MEDIUM-leaning | Price/premium increase applied automatically at renewal |
| `other_monetary_penalty` | MEDIUM | Any other monetary penalty not covered above |

### 1.2 DEFAULT (`document_type: loan`)
| Subcategory | Default severity | Definition |
|---|---|---|
| `missed_payment` | MEDIUM | Consequence defined for a single missed payment |
| `default_trigger` | HIGH | Conditions that constitute default |
| `cross_default` | HIGH | Default on one obligation triggers default on this one |
| `acceleration` | HIGH | Full balance becomes due immediately upon trigger |
| `foreclosure` | HIGH | Right to seize/sell secured property |
| `collateral_enforcement` | HIGH | Right to enforce against pledged collateral |

### 1.3 RENEWAL (`document_type: both`)
| Subcategory | Default severity | Definition |
|---|---|---|
| `auto_renewal` | MEDIUM | Contract renews automatically without explicit re-consent |
| `renewal_notice_period` | LOW–MEDIUM | Window in which the user must act to prevent renewal |
| `renewal_fee` | MEDIUM | Fee charged specifically at renewal |
| `cancellation_restriction` | MEDIUM–HIGH | Limits or penalties on cancelling |

### 1.4 LOSS_OF_RIGHTS (`document_type: both`)
| Subcategory | Default severity | Definition |
|---|---|---|
| `arbitration` | MEDIUM–HIGH | Requires disputes to go through arbitration, not court |
| `waiver` | MEDIUM–HIGH | User waives a specific right |
| `limitation_of_remedies` | MEDIUM | Caps what remedies are available to the user |
| `class_action_waiver` | HIGH | User waives right to join a class action |
| `dispute_restriction` | MEDIUM | Restricts venue, timing, or method of disputes |

### 1.5 INSURANCE (`document_type: insurance`)
| Subcategory | Default severity | Definition |
|---|---|---|
| `exclusion` | MEDIUM–HIGH | Specific event/condition not covered |
| `waiting_period` | LOW–MEDIUM | Delay before coverage becomes active |
| `deductible` | LOW–MEDIUM | Amount paid out-of-pocket before coverage applies |
| `coverage_limitation` | MEDIUM | Caps or limits on payout/coverage scope |
| `claim_condition` | MEDIUM | Conditions required for a claim to be valid |

### 1.6 INTEREST_REPAYMENT (`document_type: loan`)
| Subcategory | Default severity | Definition |
|---|---|---|
| `variable_interest` | MEDIUM | Interest rate is not fixed |
| `rate_change` | MEDIUM–HIGH | Specific conditions under which rate changes |
| `compounding` | LOW–MEDIUM | Compounding frequency/method affecting cost |
| `repayment_condition` | MEDIUM | Conditions attached to repayment |
| `payment_schedule` | LOW | Structural terms of the payment schedule |

### 1.7 TERMINATION (`document_type: both`)
| Subcategory | Default severity | Definition |
|---|---|---|
| `termination_restriction` | MEDIUM | Limits on when/how the user can terminate |
| `early_termination_fee` | MEDIUM–HIGH | Fee for terminating before term end |
| `unilateral_termination_right` | MEDIUM–HIGH | The other party can terminate without the user's consent |

### 1.8 OTHER
Reserved for genuinely novel risk patterns discovered during labeling that don't fit above — flagged for taxonomy review, not silently forced into an existing category. Additions require a taxonomy version bump (Section 6).

## 2. Severity Rules

Default severity bands above are **priors**, not final answers. The Risk Engine (AI_Risk_Engine_Design.md §3) adjusts severity using:
- Presence and magnitude of extracted financial entities (e.g., a `prepayment_penalty` with an extracted `5%` reads HIGH; with no extractable amount and vague language, it may read MEDIUM with lower confidence).
- Presence of a clear trigger/condition/consequence chain (a fully-specified condition raises confidence in the assigned severity; an ambiguous one does not raise severity, it lowers confidence).
- Document type context (e.g., `foreclosure` only applies meaningfully to secured loans).

## 3. Confidence Rules

Confidence is never assigned by the labeling category alone. Annotators (and later, the automated system) score confidence based on:
- **Evidence clarity:** is the clause's language explicit, or does it require inference?
- **Completeness:** are trigger, condition, and consequence all present in the text, or only partially?
- **Ambiguity:** could a reasonable reader interpret this clause two different ways?

A clause can be labeled `HIGH` severity with `LOW` confidence (clear pattern match but vague/incomplete language) — annotators must be trained to keep these axes independent (see Section 5).

## 4. Examples

### Positive example — `prepayment_penalty`, HIGH, confidence 0.92
> "Borrower shall pay a prepayment penalty equal to 2% of the outstanding principal if the loan is repaid in full within 24 months of disbursement."
Trigger: repayment within 24 months. Condition: full repayment. Consequence: 2% penalty. Entity: `2%`, `24 months`. Clear, complete, unambiguous → high confidence.

### Negative example — not a risk pattern
> "Borrower may make additional principal payments at any time without penalty."
Explicitly states no penalty — this is evidence *against* `prepayment_penalty`, and should be labeled as such (a clause can carry a "confirmed absence" label, not just silence) so the corpus doesn't only teach positive examples.

### Ambiguous example — `renewal_fee` vs. `auto_renewal`, MEDIUM, confidence 0.45
> "This policy will continue on the terms then in effect unless the policyholder provides notice."
No explicit fee mentioned, no explicit notice period stated — pattern suggests `auto_renewal` but is incomplete. Annotators should label this MEDIUM/LOW confidence, not skip it, and note the missing information explicitly in the annotation record (Section 5) so the model has a real "hard case" to learn calibration from.

## 5. Annotation Guidelines (summary — full process in Dataset_and_Evaluation_Spec.md)

- Every labeled example gets: `risk_category`, `risk_subcategory`, `severity`, `confidence`, `evidence_span` (exact substring), and an annotator note for ambiguous cases.
- Annotators label **absence** as well as presence where a clause explicitly rules out a risk pattern (see negative example above) — this is corpus content too, used to reduce false positives.
- Two-annotator overlap on a sample (target: 15–20% of the corpus) to compute inter-annotator agreement (Cohen's kappa) per category; categories with low agreement are flagged for definition refinement before being trusted in the Risk Engine.

## 6. JSON Schema — `ClauseAnalysis` (canonical, referenced by all documents)

```json
{
  "clause_id": "uuid",
  "document_id": "uuid",
  "clause_index": 0,
  "document_type": "loan | insurance | unknown",
  "section_heading": "string | null",
  "raw_text": "string",

  "risk_category": "financial_cost | default | renewal | loss_of_rights | insurance | interest_repayment | termination | other | null",
  "risk_subcategory": "string | null",
  "taxonomy_version": "taxonomy_v1",

  "trigger": "string | null",
  "condition": "string | null",
  "consequence": "string | null",
  "affected_party": "string | null",

  "financial_entities": [
    {"type": "percentage | amount | fee | rate | time_period", "value": "string", "unit": "string | null", "raw_text": "string"}
  ],

  "evidence_spans": [
    {"text": "string", "start_char": 0, "end_char": 0, "page_number": 0}
  ],

  "matched_patterns": [
    {"pattern_id": "uuid", "source": "cuad | scraped_indian", "similarity_score": 0.0, "lexical_score": 0.0}
  ],

  "risk_level": "HIGH | MEDIUM | LOW | UNKNOWN",
  "risk_score": 0.0,
  "confidence_level": "HIGH | MEDIUM | LOW",
  "confidence_score": 0.0,
  "abstained": false,
  "abstain_reason": "string | null",

  "explanation": "string | null",
  "explanation_grounded": "boolean | null",

  "model_version": "string",
  "created_at": "timestamp"
}
```

This schema is the single source of truth referenced by API_and_Data_Models.md (API/DB shape), AI_Risk_Engine_Design.md (which fields it populates), and Frontend_Specification_v2.md (which fields the UI renders).

## 7. Versioning

- `taxonomy_version` is stored on every `ClauseAnalysis` record. Changing a category definition, adding/removing a subcategory, or changing default severity bands requires a version bump (`taxonomy_v2`, etc.), not an in-place edit.
- The labeled corpus (Dataset_and_Evaluation_Spec.md) is versioned independently but must declare which `taxonomy_version` it was labeled against; the Risk Engine must reject or flag a mismatch between corpus version and running taxonomy version rather than silently mixing them.
