"""Entity-extraction ground truth — Phase 6 spec SS5.

Every `raw_text`/`normalized_value` pair below was verified against the
actual `entity_extraction_service.extract_financial_entities` output before
being recorded here (not hand-guessed) — see the module docstring's cases
for exactly which of the spec's "difficult cases" the current deterministic
extractor supports and which it documented-does-not (P4.7):

- `"5 percent"` (digit-led, word-form *unit*) -> **PHASE_6.5: now extracted**
  (`docs/PROVISIONAL_DECISIONS.md` P6.6) — `"percent"`/`"per cent"` are
  supported alternatives to the `"%"` symbol.
- `"five percent"` (word-form *number*) -> **not extracted**, by design
  (`docs/PROVISIONAL_DECISIONS.md` P4.7, still in scope). Recorded with
  `expected_to_be_extracted=False` so the eval harness scores "correctly
  extracted nothing" as a pass, not a silent gap.
- `"₹10,000-₹20,000"` (a range) -> extracted as **two separate `amount`
  entities**, never merged into one range concept — there is no range
  entity type. Also intentional, also recorded as the correct expectation
  (not a bug to "fix" by inventing range support here).
"""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from corpus.eval.schema import ClauseGroundTruth, DatasetSplit, GroundTruthEntity  # noqa: E402

ENTITY_CASES: tuple[ClauseGroundTruth, ...] = (
    ClauseGroundTruth(
        case_id="entity_bare_percentage",
        text="A prepayment penalty of 5% applies.",
        split=DatasetSplit.DEV,
        label_kind="positive",
        entities=(GroundTruthEntity("percentage", "5%", "5"),),
    ),
    ClauseGroundTruth(
        case_id="entity_decimal_percentage",
        text="A prepayment penalty of 5.0% applies to early repayment.",
        split=DatasetSplit.DEV,
        label_kind="positive",
        entities=(GroundTruthEntity("percentage", "5.0%", "5.0"),),
    ),
    ClauseGroundTruth(
        case_id="entity_percent_word_unit_supported",
        text="A prepayment penalty of 5 percent applies to early repayment.",
        split=DatasetSplit.DEV,
        label_kind="positive",
        entities=(GroundTruthEntity("percentage", "5 percent", "5"),),
        notes="PHASE_6.5: 'percent'/'per cent' added as word-form alternatives to the '%' "
        "symbol (docs/PROVISIONAL_DECISIONS.md P6.6) — this is a digit-led percentage with a "
        "word-form *unit* ('percent' instead of '%'), now correctly supported. Distinct from "
        "a word-form *number* (see entity_word_form_number_percentage_unsupported below), "
        "which remains unsupported.",
    ),
    ClauseGroundTruth(
        case_id="entity_word_form_number_percentage_unsupported",
        text="A prepayment penalty of five percent applies to early repayment.",
        split=DatasetSplit.DEV,
        label_kind="negative",
        entities=(GroundTruthEntity("percentage", "five percent", None, expected_to_be_extracted=False),),
        notes="Word-form *numbers* ('five' instead of '5') remain documented-unsupported "
        "(P4.7) — correct behavior is to extract nothing. This is the genuinely-still-unsupported "
        "case; it was previously conflated with the digit-led 'N percent' case above, which is "
        "a different (now-supported) pattern.",
    ),
    ClauseGroundTruth(
        case_id="entity_rate_per_month",
        text="Interest accrues at 2% per month on any overdue balance.",
        split=DatasetSplit.DEV,
        label_kind="positive",
        entities=(GroundTruthEntity("rate", "2% per month", "2"),),
    ),
    ClauseGroundTruth(
        case_id="entity_rate_per_annum",
        text="Interest accrues at 18% p.a. on the outstanding principal.",
        split=DatasetSplit.TEST,
        label_kind="positive",
        entities=(GroundTruthEntity("rate", "18% p.a.", "18"),),
    ),
    ClauseGroundTruth(
        case_id="entity_fee_amount_in_context",
        text="A processing fee of ₹10,000 applies at disbursement.",
        split=DatasetSplit.DEV,
        label_kind="positive",
        entities=(GroundTruthEntity("fee", "₹10,000", "10000"),),
        notes="'fee' keyword within the proximity window reclassifies the amount as entity_type=fee (P4.6).",
    ),
    ClauseGroundTruth(
        case_id="entity_amount_no_fee_context",
        text="The loan amount disbursed is ₹10,000 to ₹20,000 depending on eligibility.",
        split=DatasetSplit.TEST,
        label_kind="positive",
        entities=(
            GroundTruthEntity("amount", "₹10,000", "10000"),
            GroundTruthEntity("amount", "₹20,000", "20000"),
        ),
        notes="A currency range is extracted as two independent amount entities, never merged (no range type).",
    ),
    ClauseGroundTruth(
        case_id="entity_time_period_within",
        text="The borrower must notify the lender within 30 days of any change of address.",
        split=DatasetSplit.DEV,
        label_kind="positive",
        entities=(GroundTruthEntity("time_period", "30 days", "30"),),
    ),
    ClauseGroundTruth(
        case_id="entity_percentage_with_up_to_qualifier",
        text="A cancellation fee of up to 10% of the premium may apply.",
        split=DatasetSplit.DEV,
        label_kind="positive",
        entities=(GroundTruthEntity("percentage", "10%", "10"),),
        notes="'up to' is a condition-layer qualifier, not part of the entity span itself.",
    ),
    ClauseGroundTruth(
        case_id="entity_multiple_in_one_clause",
        text="A late fee of ₹500 applies if payment is not received within 15 days.",
        split=DatasetSplit.DEV,
        label_kind="positive",
        entities=(
            GroundTruthEntity("fee", "₹500", "500"),
            GroundTruthEntity("time_period", "15 days", "15"),
        ),
    ),
    ClauseGroundTruth(
        case_id="entity_none_present",
        text="Either party may terminate this agreement upon written notice.",
        split=DatasetSplit.TEST,
        label_kind="negative",
        entities=(),
        notes="No financial entity of any kind should be extracted from purely procedural text.",
    ),
    ClauseGroundTruth(
        case_id="entity_unsupported_currency_symbol",
        text="A fee of EUR 500 applies to international transfers.",
        split=DatasetSplit.DEV,
        label_kind="negative",
        entities=(GroundTruthEntity("fee", "EUR 500", None, expected_to_be_extracted=False),),
        notes="Only ₹/Rs./INR/$ are supported currency symbols (P4.7) — EUR is documented-unsupported.",
    ),
)
