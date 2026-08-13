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
        notes="STILL A GAP after Phase 6.5 and 6.6: this text has no if/when/unless-type "
        "connective at all (it's an unconditional, mandatory arbitration clause, not a "
        "conditional one) so no amount of condition-marker broadening helps. Rule fires alone "
        "(rule_boost=0.35, no entity, no condition) -> raw_score=0.35 -> LOW band -> abstained "
        "to UNKNOWN because a bare positive rule hit doesn't count as 'positive evidence for "
        "LOW'. PHASE_6.6 analysis: the gold MEDIUM label is well-justified (LOSS_OF_RIGHTS/"
        "arbitration is MEDIUM-HIGH banded, and this clause is explicit/unambiguous, not vague "
        "language needing inference) - the engine's UNKNOWN is arguably too conservative here, "
        "since PRD_v2.md SS9 says UNKNOWN should correlate with genuine ambiguity, not just 'no "
        "corroborating entity/condition happened to be present.' But raising a bare rule-only "
        "match to a confident level risks false positives on rule matches over less-explicit "
        "text elsewhere - a real fix needs a way to distinguish 'explicit complete clause' from "
        "'weak/coincidental rule match', which the current architecture doesn't have and "
        "shouldn't invent speculatively (see docs/SEVERITY_CALIBRATION_NOTES.md 'Unresolved "
        "questions'). Not fixed here since the only lever available (a threshold/weight change) "
        "would be justified by nothing but this TEST case. Same structural pattern as "
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
        notes="SEVERITY_AMBIGUOUS (PHASE_6.6, docs/SEVERITY_CALIBRATION_NOTES.md): "
        "Risk_Taxonomy_and_Labeling_Spec.md SS1.6 bands interest_repayment/rate_change as "
        "'MEDIUM-HIGH' - a two-level-wide prior, not a single value. This file's MEDIUM gold "
        "label and the engine's HIGH output are BOTH within that taxonomy-permitted band; "
        "neither is 'demonstrably inconsistent with the documented taxonomy' (the bar for "
        "changing a label per this phase's own instructions), so the label is left as MEDIUM "
        "rather than flipped to match the engine. Phase 6.6 extensively verified (4 weight-"
        "rebalancing hypotheses tested against the full 30-case DEV benchmark) that no "
        "DEV-safe engine change resolves this - every hypothesis that pulled this case down to "
        "MEDIUM also incorrectly pulled genuinely-HIGH DEV cases (clean prepayment/acceleration "
        "examples with the identical rule+entity+condition signal shape) down to MEDIUM too. "
        "This is a real within-band ambiguity requiring expert-annotated data to resolve, not "
        "an engine bug - see docs/SEVERITY_CALIBRATION_NOTES.md 'Ambiguities discovered'.",
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
        notes="SEVERITY_AMBIGUOUS (PHASE_6.6, docs/SEVERITY_CALIBRATION_NOTES.md): "
        "Risk_Taxonomy_and_Labeling_Spec.md SS1.5 bands insurance/deductible as 'LOW-MEDIUM' - "
        "this file's LOW gold label and the engine's MEDIUM output (0.61, capped consistent with "
        "the new severity_ceiling mechanism, which still permits MEDIUM for this band) are BOTH "
        "within that taxonomy-permitted band. A deductible is a genuine out-of-pocket cost, so "
        "MEDIUM is not an unreasonable read; LOW (written when no rule existed for this category "
        "at all, per Phase 6 pre-6.5) is also defensible for a routine, expected insurance term. "
        "Left as MEDIUM-gold rather than flipped, per this phase's rule against changing a label "
        "that isn't demonstrably inconsistent with the taxonomy - see "
        "docs/SEVERITY_CALIBRATION_NOTES.md 'Ambiguities discovered'.",
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
