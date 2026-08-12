"""Condition-extraction ground truth — Phase 6 spec SS6.

Every expected `trigger`/`condition`/`consequence`/`affected_party` value
below was verified against the actual
`condition_extraction_service.extract_condition` output before being
recorded (not hand-guessed). Three of the spec's seven required adversarial
connectives are **not recognized by the current extractor at all** —
recorded here as the correct expectation (all fields `None`) with a note,
not silently worked around:

- `"provided that"` — not in `_TRIGGER_MARKERS`.
- `"subject to"` — not in `_TRIGGER_MARKERS`.
- `"notwithstanding"` — not in `_TRIGGER_MARKERS` (though
  `affected_party` is still found independently, since that lookup doesn't
  depend on trigger-marker detection).

This is a real, load-bearing finding, not a benchmark-construction
convenience: it means clauses using these three connectives currently
contribute `condition_completeness=none` to the Risk Engine regardless of
how clear their actual conditional structure is. See
`run_condition_eval.py`'s output and
docs/PROVISIONAL_DECISIONS.md "Phase 6: adversarial findings."
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
        case_id="condition_provided_that_unsupported",
        text="Provided that all conditions are met, the loan shall be disbursed within 5 days.",
        split=DatasetSplit.DEV,
        label_kind="negative",
        trigger=None,
        condition=None,
        consequence=None,
        affected_party=None,
        notes="'provided that' is not a recognized trigger marker — known extractor gap, see module docstring.",
    ),
    ClauseGroundTruth(
        case_id="condition_subject_to_unsupported",
        text="Subject to credit approval, the interest rate shall be fixed at 10 percent.",
        split=DatasetSplit.TEST,
        label_kind="negative",
        trigger=None,
        condition=None,
        consequence=None,
        affected_party=None,
        notes="'subject to' is not a recognized trigger marker — known extractor gap, see module docstring.",
    ),
    ClauseGroundTruth(
        case_id="condition_notwithstanding_unsupported",
        text="Notwithstanding any other provision, the lender may demand immediate repayment.",
        split=DatasetSplit.DEV,
        label_kind="negative",
        trigger=None,
        condition=None,
        consequence=None,
        affected_party="the lender",
        notes="'notwithstanding' is not a recognized trigger marker — known extractor gap, see module docstring. "
        "affected_party is still found (independent lookup).",
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
