"""Abstention (UNKNOWN) ground truth — Phase 6 spec SS10.

Deliberately includes cases on **both** sides of the question the phase
brief asks: "are genuinely ambiguous clauses more likely to become UNKNOWN,
or is UNKNOWN simply used because the engine is under-confident everywhere?"
`ambiguous=True` marks the former group (should abstain because the text
itself is genuinely unclear); `ambiguous=False` + `expected_abstention=False`
marks clean, unambiguous clauses that a correctly-working system must
**not** abstain on (a "false abstention" probe) — abstaining on these would
indicate the engine is under-confident rather than correctly selective.
"""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from app.models.enums import RiskCategory, RiskLevel  # noqa: E402
from corpus.eval.schema import ClauseGroundTruth, DatasetSplit  # noqa: E402

ABSTENTION_CASES: tuple[ClauseGroundTruth, ...] = (
    # -- Genuinely ambiguous: SHOULD abstain --------------------------------
    ClauseGroundTruth(
        case_id="abstain_vague_reference",
        text="Prepayment provisions may apply under certain circumstances.",
        split=DatasetSplit.DEV,
        label_kind="ambiguous",
        risk_level=RiskLevel.UNKNOWN,
        expected_abstention=True,
        ambiguous=True,
        notes="No amount, no clear trigger — genuinely underspecified, not merely under-confident.",
    ),
    ClauseGroundTruth(
        case_id="abstain_cross_reference_only",
        text="Prepayment terms are described in Section 7.",
        split=DatasetSplit.DEV,
        label_kind="ambiguous",
        risk_level=RiskLevel.UNKNOWN,
        expected_abstention=True,
        ambiguous=True,
        notes="Real evidence exists but is out of scope for a single-clause analysis (cross-reference).",
    ),
    ClauseGroundTruth(
        case_id="abstain_low_segmentation_confidence",
        text="Borrower shall pay a prepayment penalty equal to 5% if repaid within 24 months.",
        split=DatasetSplit.DEV,
        label_kind="ambiguous",
        risk_level=RiskLevel.UNKNOWN,
        expected_abstention=True,
        ambiguous=True,
        low_confidence_flag=True,
        notes="Otherwise-clear text, but the clause boundary itself is unreliable (Phase 5 P5.3-adjacent rule).",
    ),
    ClauseGroundTruth(
        case_id="abstain_wrong_document_type_category",
        text="A waiting period of 90 days applies before coverage under this policy becomes effective.",
        split=DatasetSplit.TEST,
        label_kind="ambiguous",
        risk_level=RiskLevel.UNKNOWN,
        expected_abstention=True,
        ambiguous=True,
        notes="Insurance-only category pattern on a loan document — doc_type_relevance gate should force UNKNOWN.",
    ),
    ClauseGroundTruth(
        case_id="abstain_administrative_fee_vague",
        text="An administrative fee may apply.",
        split=DatasetSplit.TEST,
        label_kind="ambiguous",
        risk_level=RiskLevel.UNKNOWN,
        expected_abstention=True,
        ambiguous=True,
        notes="No amount, no rule match, no clear category — Phase 6 spec case F.",
    ),
    # -- Clear, unambiguous: must NOT abstain (false-abstention probes) -----
    ClauseGroundTruth(
        case_id="no_abstain_clear_high",
        text=(
            "Borrower shall pay a prepayment penalty equal to 5% of the outstanding "
            "principal if the loan is repaid in full within 24 months of disbursement."
        ),
        split=DatasetSplit.DEV,
        label_kind="positive",
        risk_category=RiskCategory.FINANCIAL_COST,
        risk_subcategory="prepayment_penalty",
        risk_level=RiskLevel.HIGH,
        expected_abstention=False,
        ambiguous=False,
    ),
    ClauseGroundTruth(
        case_id="no_abstain_clear_low",
        text="Borrower may prepay at any time without penalty.",
        split=DatasetSplit.DEV,
        label_kind="negative",
        risk_category=RiskCategory.FINANCIAL_COST,
        risk_subcategory="prepayment_penalty",
        risk_level=RiskLevel.LOW,
        expected_abstention=False,
        ambiguous=False,
        notes="Explicit, unambiguous confirmed-absence language — abstaining here would be under-confidence.",
    ),
    ClauseGroundTruth(
        case_id="no_abstain_clear_medium",
        text="In case of late payment, acceleration of the entire outstanding balance shall apply immediately.",
        split=DatasetSplit.TEST,
        label_kind="positive",
        risk_category=RiskCategory.DEFAULT,
        risk_subcategory="acceleration",
        risk_level=RiskLevel.MEDIUM,
        expected_abstention=False,
        ambiguous=False,
    ),
)
