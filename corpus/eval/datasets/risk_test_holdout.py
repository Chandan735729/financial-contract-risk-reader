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

**What Phase 6 found:** roughly half of these cases failed (`known_gap=True`),
tracing to two structural limitations, not a scoring bug: (1) the reference
corpus was empty, so retrieval contributed zero signal and every detection
depended entirely on 5 narrow rules; (2) those 5 rules covered a small slice
of the taxonomy and were phrasing-literal.

**PHASE_6.5 update:** 3 of the 3 phrasing-literal "classification_error"
cases (`test_prepayment_fee_wording_variant`,
`test_termination_without_penalty_wording_variant`,
`test_auto_renewal_annually_wording_variant`) are now fixed — the relevant
rules' primary patterns were generalized to cover the wording variant, and
each is now `known_gap=False`. The 4 `corpus_gap` cases now have real rule
coverage (`docs/PROVISIONAL_DECISIONS.md` P6.6 item 5) and no longer return
a pure "no signal" `UNKNOWN` — but 3 of the 4 (`test_interest_rate_change_no_rule_coverage`,
`test_insurance_exclusion_no_rule_coverage`, `test_deductible_no_rule_coverage`)
still don't match this file's specific gold label exactly (a severity-level
mismatch or a wording variant the new rule still doesn't catch), and
`test_standalone_jury_waiver_no_rule_coverage` and
`test_arbitration_no_condition_marker` share a structural scoring pattern
(a rule fires alone, with no corroborating entity or condition chain, and
the engine's LOW-band abstention logic — "no positive evidence for LOW" —
treats that the same as no signal at all, abstaining to UNKNOWN instead of
MEDIUM). Fixing that structural pattern would require a weight/threshold
change, which was deliberately not made this phase specifically because the
only justification for it would be these TEST cases — see each case's
`notes` below and the Phase 6.5 final report for the honest, un-obscured
before/after picture. `matched_patterns=()` remains deliberate on every
case below: TEST is scored using only the rule/entity/condition signals a
real 5-rule-then-13-rule production system would have, never a fabricated
retrieval hit.
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
        notes="PHASE_6.5 FIXED: prepayment_penalty's primary pattern broadened to include "
        "'payoff'/'ahead of schedule'/'settles the loan' phrasing (a general concept, not this "
        "sentence specifically) - now correctly predicts HIGH.",
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
        notes="STILL A GAP after Phase 6.5: this text has no if/when/unless-type connective at "
        "all (it's an unconditional, mandatory arbitration clause, not a conditional one) so no "
        "amount of condition-marker broadening helps. Rule fires alone (rule_boost=0.35, no "
        "entity, no condition) -> raw_score=0.35 -> LOW band -> abstained to UNKNOWN because a "
        "bare positive rule hit doesn't count as 'positive evidence for LOW'. The only lever "
        "that would flip this is a weight/threshold change, which would be justified by nothing "
        "but this one TEST case - deliberately not done (see corpus/eval/README.md and the "
        "Phase 6.5 final report). Same structural pattern as "
        "test_standalone_jury_waiver_no_rule_coverage below.",
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
        notes="PHASE_6.5 PARTIAL: a new interest_rate_change rule now covers this category and "
        "fires correctly (no longer UNKNOWN) - the stated 'no rule coverage' problem is fixed. "
        "But with the rule + a strong rate entity (3%, magnitude bonus) + a full condition "
        "chain (consequence-before-trigger fix) all present, the formula now reaches HIGH "
        "(0.76), one band above this file's MEDIUM gold label. Left as-is rather than "
        "weight-tuned to force MEDIUM on this one TEST case - see Phase 6.5 final report.",
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
        notes="STILL A GAP after Phase 6.5: a new insurance_exclusion rule exists "
        "(primary 'exclu(de/sion/...)', to deliberately avoid self-negating on its own 'not "
        "liable'-style phrasing - see docs/PROVISIONAL_DECISIONS.md P6.9), but this exact "
        "sentence uses 'shall not be liable for any claim' instead of the word 'exclu...' at "
        "all, so the rule's primary term never matches. Not broadened to catch 'not liable' "
        "phrasing specifically, since that phrase's own 'not' would risk the same self-negation "
        "trap 'waive'/'excluding' were kept out of the negation-cue list for - a real remaining "
        "gap, not silently patched around this one sentence.",
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
        notes="PHASE_6.5 PARTIAL: a new insurance_deductible rule now covers this category and "
        "fires correctly (no longer UNKNOWN) - the stated 'no rule coverage' problem is fixed. "
        "But rule + amount entity together reach MEDIUM (0.61), not this file's LOW gold label. "
        "A deductible is itself a real out-of-pocket cost worth surfacing, so MEDIUM is at least "
        "as taxonomically defensible as the original LOW guess (written when no rule existed at "
        "all) - left as-is rather than weight-tuned to force a match. See Phase 6.5 final report.",
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
        notes="STILL A GAP after Phase 6.5: a new standalone_rights_waiver rule now covers this "
        "category and correctly fires (rule_matches shows a positive hit) - the stated 'no rule "
        "coverage' problem is fixed. But this text has no entity and no condition connective, so "
        "the rule-alone raw_score (0.35) lands in the LOW band and gets abstained to UNKNOWN by "
        "the same structural pattern as test_arbitration_no_condition_marker above - see that "
        "case's notes.",
    ),
    ClauseGroundTruth(
        case_id="test_termination_without_penalty_wording_variant",
        text="Either party may terminate this agreement with 60 days written notice, without cause and without penalty.",
        split=DatasetSplit.TEST,
        label_kind="negative",
        risk_category=RiskCategory.TERMINATION,
        risk_level=RiskLevel.LOW,
        notes="PHASE_6.5 FIXED: early_termination_fee's primary pattern broadened to include a "
        "generic 'terminate this/the agreement' alternative (not requiring the literal word "
        "'early') - the rule now fires and is correctly negated by 'without cause and without "
        "penalty', reaching LOW.",
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
        notes="PHASE_6.5 FIXED: auto_renewal_notice's primary pattern broadened to include "
        "'renews annually/each year/every year', and its secondary term broadened from bare "
        "'notice' to also accept 'cancel(s/led/lation)' (an equally common escape-hatch "
        "phrasing) - now correctly predicts MEDIUM.",
    ),
)
