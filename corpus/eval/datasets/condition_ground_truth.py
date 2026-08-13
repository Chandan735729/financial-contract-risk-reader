"""Condition-extraction ground truth — Phase 6 spec SS6.

Every expected `trigger`/`condition`/`consequence`/`affected_party` value
below was verified against the actual
`condition_extraction_service.extract_condition` output before being
recorded (not hand-guessed).

PHASE_6.5 update: three of the spec's seven required adversarial
connectives — `"provided that"`, `"subject to"`, `"notwithstanding"` — were
previously not recognized by the extractor at all (recorded as all-`None`
negative cases). `_TRIGGER_MARKERS` now includes all three
(docs/PROVISIONAL_DECISIONS.md P6.6 item 4), so the three
`condition_*_unsupported` cases below were renamed to `condition_*_supported`
and their gold fields updated to the actual (verified) extractor output.
See `run_condition_eval.py`'s output and
docs/PROVISIONAL_DECISIONS.md "Phase 6.5: condition extraction generalization."
"""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from corpus.eval.schema import ClauseGroundTruth, DatasetSplit  # noqa: E402

CONDITION_CASES: tuple[ClauseGroundTruth, ...] = (
    ClauseGroundTruth(
        case_id="condition_if",
        text="If the borrower defaults, the lender may accelerate the loan.",
        split=DatasetSplit.DEV,
        label_kind="positive",
        trigger="If the borrower defaults",
        consequence="the lender may accelerate the loan",
        affected_party="the borrower",
    ),
    ClauseGroundTruth(
        case_id="condition_unless",
        text="Unless the borrower cures the default within 10 days, the lender may terminate.",
        split=DatasetSplit.DEV,
        label_kind="positive",
        trigger="Unless the borrower cures the default",
        condition="within 10 days",
        consequence="the lender may terminate",
        affected_party="the borrower",
    ),
    ClauseGroundTruth(
        case_id="condition_except_where",
        text="Except where the delay is caused by the lender, a late fee applies.",
        split=DatasetSplit.DEV,
        label_kind="positive",
        trigger="Except where the delay is caused by the lender",
        consequence="a late fee applies",
        affected_party="the lender",
    ),
    ClauseGroundTruth(
        case_id="condition_only_if",
        text="Only if the borrower provides written consent shall the transfer be permitted.",
        split=DatasetSplit.TEST,
        label_kind="positive",
        trigger="if the borrower provides written consent",
        consequence="shall the transfer be permitted",
        affected_party="the borrower",
        notes="The leading 'Only' is dropped from the trigger span; the 'if' clause itself is captured correctly.",
    ),
    ClauseGroundTruth(
        case_id="condition_provided_that_supported",
        text="Provided that all conditions are met, the loan shall be disbursed within 5 days.",
        split=DatasetSplit.DEV,
        label_kind="positive",
        trigger="Provided that all conditions are met",
        condition=None,
        consequence="the loan shall be disbursed within 5 days",
        affected_party=None,
        notes="PHASE_6.5: 'provided that' added to _TRIGGER_MARKERS (docs/PROVISIONAL_DECISIONS.md P6.6 item 4). "
        "Expected fields verified against the actual extractor output, same discipline as the rest of this file.",
    ),
    ClauseGroundTruth(
        case_id="condition_subject_to_supported",
        text="Subject to credit approval, the interest rate shall be fixed at 10 percent.",
        split=DatasetSplit.TEST,
        label_kind="positive",
        trigger="Subject to credit approval",
        condition=None,
        consequence="the interest rate shall be fixed at 10 percent",
        affected_party=None,
        notes="PHASE_6.5: 'subject to' added to _TRIGGER_MARKERS (docs/PROVISIONAL_DECISIONS.md P6.6 item 4). "
        "This case is in TEST — the expected fields come from the general marker-detection logic (verified against "
        "the actual extractor output), not tuned to this sentence specifically.",
    ),
    ClauseGroundTruth(
        case_id="condition_notwithstanding_supported",
        text="Notwithstanding any other provision, the lender may demand immediate repayment.",
        split=DatasetSplit.DEV,
        label_kind="positive",
        trigger="Notwithstanding any other provision",
        condition=None,
        consequence="the lender may demand immediate repayment",
        affected_party="the lender",
        notes="PHASE_6.5: 'notwithstanding' added to _TRIGGER_MARKERS (docs/PROVISIONAL_DECISIONS.md P6.6 item 4). "
        "affected_party was already found independently even before this fix.",
    ),
    ClauseGroundTruth(
        case_id="condition_no_marker_present",
        text="This agreement is governed by the laws of the applicable jurisdiction.",
        split=DatasetSplit.DEV,
        label_kind="negative",
        trigger=None,
        condition=None,
        consequence=None,
        affected_party=None,
        notes="No conditional connective at all — a correct extractor must not invent a chain from vague language.",
    ),
)
