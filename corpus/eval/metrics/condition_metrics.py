"""Condition-extraction evaluation metrics — Phase 6 spec SS6.

Per-field accuracy (`trigger`/`condition`/`consequence`/`affected_party`) is
"predicted field == gold field," exact string match — not keyword presence
(Phase 6 spec SS6: "Do not treat keyword presence as sufficient"). A gold
field of `None` is only counted correct if the prediction is also `None`
(a genuine "correctly found nothing" case, not a free pass).

Chain completeness compares the *shape* (which fields are populated, not
their exact text) between predicted and gold, classified into
`none`/`partial`/`full` using the same rule `risk_engine.score_conditions`
uses (trigger and consequence both present -> full).
"""

from __future__ import annotations

import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from corpus.eval.schema import ClauseGroundTruth  # noqa: E402

ConditionField = Literal["trigger", "condition", "consequence", "affected_party"]
_FIELDS: tuple[ConditionField, ...] = ("trigger", "condition", "consequence", "affected_party")


class PredictedConditionLike(Protocol):
    @property
    def trigger(self) -> str | None: ...
    @property
    def condition(self) -> str | None: ...
    @property
    def consequence(self) -> str | None: ...
    @property
    def affected_party(self) -> str | None: ...


@dataclass(frozen=True, slots=True)
class PerFieldConditionMetrics:
    field: ConditionField
    accuracy: float
    # Of gold-populated instances of this field, how many were found at all
    # (regardless of exact text match) — a looser "did we notice this field
    # exists" signal alongside the exact-match `accuracy`.
    presence_recall: float
    support: int


@dataclass(frozen=True, slots=True)
class ConditionEvalReport:
    case_count: int
    by_field: tuple[PerFieldConditionMetrics, ...]
    chain_completeness_accuracy: float  # predicted completeness label == gold completeness label


def _completeness_label(trigger: str | None, consequence: str | None, condition: str | None) -> str:
    if trigger and consequence:
        return "full"
    if trigger or consequence or condition:
        return "partial"
    return "none"


def evaluate_conditions(
    cases: Sequence[tuple[ClauseGroundTruth, PredictedConditionLike]],
) -> ConditionEvalReport:
    """`cases`: list of `(ground_truth, predicted)` pairs, where `predicted`
    is `condition_extraction_service.ExtractedCondition` (or any object with
    `trigger`/`condition`/`consequence`/`affected_party` attributes)."""
    field_correct: dict[str, int] = dict.fromkeys(_FIELDS, 0)
    field_support: dict[str, int] = dict.fromkeys(_FIELDS, 0)
    field_present_found: dict[str, int] = dict.fromkeys(_FIELDS, 0)

    completeness_correct = 0

    for gt, predicted in cases:
        for field in _FIELDS:
            gold_value = getattr(gt, field)
            predicted_value = getattr(predicted, field)
            if gold_value == predicted_value:
                field_correct[field] += 1
            if gold_value is not None:
                field_support[field] += 1
                if predicted_value is not None:
                    field_present_found[field] += 1

        gold_label = _completeness_label(gt.trigger, gt.consequence, gt.condition)
        predicted_label = _completeness_label(predicted.trigger, predicted.consequence, predicted.condition)
        if gold_label == predicted_label:
            completeness_correct += 1

    n = len(cases)
    by_field = tuple(
        PerFieldConditionMetrics(
            field=field,
            accuracy=(field_correct[field] / n) if n > 0 else 0.0,
            presence_recall=(
                (field_present_found[field] / field_support[field]) if field_support[field] > 0 else 0.0
            ),
            support=field_support[field],
        )
        for field in _FIELDS
    )

    return ConditionEvalReport(
        case_count=n,
        by_field=by_field,
        chain_completeness_accuracy=(completeness_correct / n) if n > 0 else 0.0,
    )
