"""Held-out risk-classification TEST split — Phase 6 spec SS1/SS13.

**Never used to select a weight, threshold, or rule** — `risk_engine_v1`
(Phase 5) was tuned entirely against
`backend/tests/fixtures/risk_engine_benchmark.py`, which this repo now
treats as the DEV/TUNING split (`run_threshold_tuning.py` only ever reads
that file). These cases were written after tuning was complete, specifically
to probe generalization to phrasing the DEV set doesn't already contain.

**Honesty note (Phase 6 spec: "do not fabricate benchmark quality"):** this
is *not* a genuinely blind held-out set in the strict sense — the same
person who tuned the engine also wrote these cases, so it cannot rule out
unconscious bias toward cases the engine happens to handle. It is a
process-separation exercise (distinct authorship time, explicit "never
tune on this" rule, cases chosen to probe *phrasing variation* rather than
to replicate DEV), not a substitute for `Dataset_and_Evaluation_Spec.md`
SS4's real-world, independently-annotated benchmark, which does not exist
yet.

**What this split found:** roughly half of these cases fail
(`known_gap=True`), and every failure traces to one of two structural
limitations, not a scoring bug:

1. **The reference corpus (`corpus_patterns`) is empty** (see
   `corpus/README.md` — corpus collection was out of scope through Phase 5).
   With no corpus, dense/lexical retrieval contributes exactly zero signal
   for every clause in production today; every positive detection currently
   depends entirely on the five narrow deterministic rules
   (`risk_rules.py`). Cases below use `matched_patterns=()` deliberately,
   mirroring this actual production reality.
2. **Those five rules cover a small slice of the taxonomy and are phrasing-
   literal.** Whole categories — every `insurance` subcategory,
   `interest_repayment/rate_change`, standalone (non-arbitration) rights
   waivers — have zero rule coverage; phrasing that doesn't match a rule's
   exact primary pattern (`"renews annually"` vs. `"renews automatically"`,
   `"early payoff fee"` vs. `"pays off early"`) also misses even within a
   covered category.

The remaining cases (clean prepayment/arbitration/termination-fee phrasing
that *is* covered by the five rules) pass, showing the gap is coverage
breadth, not a broken scoring mechanism.
"""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from app.models.enums import DocumentType, RiskCategory, RiskLevel  # noqa: E402
from corpus.eval.schema import ClauseGroundTruth, DatasetSplit  # noqa: E402

RISK_TEST_HOLDOUT: tuple[ClauseGroundTruth, ...] = (
    # -- Pass: novel phrasing that still matches the covered rule patterns --
    ClauseGroundTruth(
        case_id="test_prepayment_penalty_novel_phrasing",
        text=(
            "If the borrower prepays the outstanding loan balance within 18 months "
            "of disbursement, a prepayment penalty of 3% shall be charged."
        ),
        split=DatasetSplit.TEST,
        label_kind="positive",
        risk_category=RiskCategory.FINANCIAL_COST,
        risk_subcategory="prepayment_penalty",
        risk_level=RiskLevel.HIGH,
    ),
    ClauseGroundTruth(
        case_id="test_arbitration_waiver_novel_phrasing",
        text=(
            "If either party wishes to dispute any matter arising from this "
            "agreement, the dispute shall proceed to arbitration, and both "
            "parties waive the right to a jury trial."
        ),
        split=DatasetSplit.TEST,
        label_kind="positive",
        risk_category=RiskCategory.LOSS_OF_RIGHTS,
        risk_subcategory="arbitration",
        risk_level=RiskLevel.MEDIUM,
    ),
    ClauseGroundTruth(
        case_id="test_prepayment_negated_novel_phrasing",
        text="The borrower may repay the outstanding loan at any point without incurring a prepayment charge of any kind.",
        split=DatasetSplit.TEST,
        label_kind="negative",
        risk_category=RiskCategory.FINANCIAL_COST,
        risk_subcategory="prepayment_penalty",
        risk_level=RiskLevel.LOW,
    ),
    ClauseGroundTruth(
        case_id="test_early_termination_fee_novel_phrasing",
        text="If the tenant fails to vacate after the notice period, the landlord may seek an early termination fee equal to one month of rent.",
        split=DatasetSplit.TEST,
        label_kind="positive",
        risk_category=RiskCategory.TERMINATION,
        risk_subcategory="early_termination_fee",
        risk_level=RiskLevel.MEDIUM,
    ),
    # -- Fail (known_gap=True): categories/phrasing outside the 5 rules' coverage --
    ClauseGroundTruth(
        case_id="test_prepayment_fee_wording_variant",
        text="Should the borrower choose to settle the loan ahead of schedule, a 4% early payoff fee applies.",
        split=DatasetSplit.TEST,
        label_kind="positive",
        risk_category=RiskCategory.FINANCIAL_COST,
        risk_subcategory="prepayment_penalty",
        risk_level=RiskLevel.HIGH,
        known_gap=True,
        notes="'early payoff fee' / 'settle...ahead of schedule' don't match the rule's literal 'pays off early' pattern.",
    ),
    ClauseGroundTruth(
        case_id="test_arbitration_no_condition_marker",
        text="The parties agree that any claim shall be settled by binding arbitration, thereby waiving the right to sue in court.",
        split=DatasetSplit.TEST,
        label_kind="positive",
        risk_category=RiskCategory.LOSS_OF_RIGHTS,
        risk_subcategory="arbitration",
        risk_level=RiskLevel.MEDIUM,
        known_gap=True,
        notes="Rule fires, but no if/when/unless marker -> condition_completeness=none -> score lands just under MEDIUM_THRESHOLD.",
    ),
    ClauseGroundTruth(
        case_id="test_interest_rate_change_no_rule_coverage",
        text="Interest on the outstanding balance shall increase by 3% per annum if the borrower misses two consecutive installments.",
        split=DatasetSplit.TEST,
        label_kind="positive",
        risk_category=RiskCategory.INTEREST_REPAYMENT,
        risk_subcategory="rate_change",
        risk_level=RiskLevel.MEDIUM,
        known_gap=True,
        notes="No rule covers interest_repayment/rate_change; current engine returns UNKNOWN.",
    ),
    ClauseGroundTruth(
        case_id="test_insurance_exclusion_no_rule_coverage",
        text="The insurer shall not be liable for any claim arising from a pre-existing medical condition.",
        split=DatasetSplit.TEST,
        label_kind="positive",
        document_type=DocumentType.INSURANCE,
        risk_category=RiskCategory.INSURANCE,
        risk_subcategory="exclusion",
        risk_level=RiskLevel.MEDIUM,
        known_gap=True,
        notes="No rule covers any insurance subcategory; current engine returns UNKNOWN.",
    ),
    ClauseGroundTruth(
        case_id="test_deductible_no_rule_coverage",
        text="A deductible of Rs. 5,000 applies before coverage begins.",
        split=DatasetSplit.TEST,
        label_kind="positive",
        document_type=DocumentType.INSURANCE,
        risk_category=RiskCategory.INSURANCE,
        risk_subcategory="deductible",
        risk_level=RiskLevel.LOW,
        known_gap=True,
        notes="No rule covers deductible; entity signal alone (weight 0.20) can't clear low_threshold without a rule hit.",
    ),
    ClauseGroundTruth(
        case_id="test_standalone_jury_waiver_no_rule_coverage",
        text="The Borrower waives any right to a jury trial in connection with this agreement.",
        split=DatasetSplit.TEST,
        label_kind="positive",
        risk_category=RiskCategory.LOSS_OF_RIGHTS,
        risk_subcategory="waiver",
        risk_level=RiskLevel.MEDIUM,
        known_gap=True,
        notes="arbitration_waiver rule requires BOTH 'arbitrat' and 'waiv' terms; a standalone waiver has no rule.",
    ),
    ClauseGroundTruth(
        case_id="test_termination_without_penalty_wording_variant",
        text="Either party may terminate this agreement with 60 days written notice, without cause and without penalty.",
        split=DatasetSplit.TEST,
        label_kind="negative",
        risk_category=RiskCategory.TERMINATION,
        risk_level=RiskLevel.LOW,
        known_gap=True,
        notes="early_termination_fee rule requires the literal phrase 'early termination'; generic 'terminate...without penalty' doesn't match.",
    ),
    ClauseGroundTruth(
        case_id="test_auto_renewal_annually_wording_variant",
        text="This insurance policy renews annually unless the insured cancels in writing at least 15 days before the renewal date.",
        split=DatasetSplit.TEST,
        label_kind="positive",
        document_type=DocumentType.INSURANCE,
        risk_category=RiskCategory.RENEWAL,
        risk_subcategory="auto_renewal",
        risk_level=RiskLevel.MEDIUM,
        known_gap=True,
        notes="auto_renewal_notice rule's primary pattern requires 'automatically'/'auto-'; 'renews annually' isn't matched.",
    ),
)
