"""Risk Engine evaluation metrics — Dataset_and_Evaluation_Spec.md SS5
("Classification (Risk Engine output)"), Phase 5 spec SS24.

Operates on `(predicted, gold)` `RiskLevel` pairs (one per benchmark clause)
plus the underlying `RiskResult`s, so it can also report the evidence/
signal-disagreement diagnostics Phase 5 spec SS24 asks for. Does not itself
decide whether a benchmark is production-representative — see
`corpus/eval/run_risk_engine_eval.py` and
docs/PROVISIONAL_DECISIONS.md "Phase 5: risk engine evaluation is
synthetic-only" for that caveat.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.models.enums import RiskCategory, RiskLevel
from app.services.risk_engine import RiskResult

_LEVELS: tuple[RiskLevel, ...] = (RiskLevel.HIGH, RiskLevel.MEDIUM, RiskLevel.LOW, RiskLevel.UNKNOWN)
_RISKY_LEVELS = frozenset({RiskLevel.HIGH, RiskLevel.MEDIUM})

# Signal agreement below this is counted as "disagreement" for the
# diagnostic disagreement-rate metric — an arbitrary but documented cut
# point at the midpoint of the [0, 1] agreement scale.
_DISAGREEMENT_THRESHOLD = 0.5


@dataclass(frozen=True, slots=True)
class PerLevelMetrics:
    level: RiskLevel
    precision: float
    recall: float
    f1: float
    support: int  # number of gold-label instances of this level in the benchmark


@dataclass(frozen=True, slots=True)
class PerCategoryMetrics:
    """PHASE_6.5: `PerLevelMetrics` alone can't show *which* taxonomy
    category improved — only HIGH/MEDIUM/LOW/UNKNOWN in aggregate. Same
    precision/recall/F1 shape, keyed on `RiskCategory` (`r.risk_category`,
    the engine's *candidate* category, vs. the gold `risk_category`) instead
    of `RiskLevel`. Only categories appearing in `gold_category` and/or the
    predicted categories are included (not the full `RiskCategory` enum) —
    a category the benchmark never exercises isn't reported as a spurious
    0.00; a category the engine over-predicts still gets its precision
    reported even with `support=0`."""

    category: RiskCategory
    precision: float
    recall: float
    f1: float
    support: int


@dataclass(frozen=True, slots=True)
class RiskEvalReport:
    case_count: int
    per_level: tuple[PerLevelMetrics, ...]
    per_category: tuple[PerCategoryMetrics, ...]
    macro_f1: float
    high_risk_precision: float
    high_risk_recall: float
    false_positive_rate: float  # gold safe/unknown predicted as HIGH/MEDIUM
    false_negative_rate: float  # gold HIGH/MEDIUM predicted as safe/unknown
    abstention_rate: float
    high_medium_with_verified_evidence_rate: float
    evidence_failure_rate: float
    signal_disagreement_rate: float


def _precision_recall_f1(
    predicted: list[RiskLevel], gold: list[RiskLevel], level: RiskLevel
) -> PerLevelMetrics:
    tp = sum(1 for p, g in zip(predicted, gold, strict=True) if p == level and g == level)
    fp = sum(1 for p, g in zip(predicted, gold, strict=True) if p == level and g != level)
    fn = sum(1 for p, g in zip(predicted, gold, strict=True) if p != level and g == level)
    support = sum(1 for g in gold if g == level)

    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0.0
    return PerLevelMetrics(level=level, precision=precision, recall=recall, f1=f1, support=support)


def _category_precision_recall_f1(
    predicted: list[RiskCategory | None], gold: list[RiskCategory | None], category: RiskCategory
) -> PerCategoryMetrics:
    tp = sum(1 for p, g in zip(predicted, gold, strict=True) if p == category and g == category)
    fp = sum(1 for p, g in zip(predicted, gold, strict=True) if p == category and g != category)
    fn = sum(1 for p, g in zip(predicted, gold, strict=True) if p != category and g == category)
    support = sum(1 for g in gold if g == category)

    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0.0
    return PerCategoryMetrics(category=category, precision=precision, recall=recall, f1=f1, support=support)


def evaluate_risk_engine(
    results: list[RiskResult],
    gold: list[RiskLevel],
    *,
    gold_category: list[RiskCategory | None] | None = None,
) -> RiskEvalReport:
    """`results`/`gold` must be the same length and index-aligned (one
    `RiskResult` + one gold `RiskLevel` per benchmark case). `gold_category`
    is optional (PHASE_6.5 addition) — omit it (or pass all-`None`) for
    benchmarks that don't annotate a gold category; `per_category` is then
    simply empty rather than an error."""
    if len(results) != len(gold):
        raise ValueError("results and gold must be the same length")
    if gold_category is not None and len(gold_category) != len(results):
        raise ValueError("gold_category must be the same length as results/gold")
    if not results:
        return RiskEvalReport(
            case_count=0,
            per_level=tuple(_precision_recall_f1([], [], level) for level in _LEVELS),
            per_category=(),
            macro_f1=0.0,
            high_risk_precision=0.0,
            high_risk_recall=0.0,
            false_positive_rate=0.0,
            false_negative_rate=0.0,
            abstention_rate=0.0,
            high_medium_with_verified_evidence_rate=0.0,
            evidence_failure_rate=0.0,
            signal_disagreement_rate=0.0,
        )

    predicted = [r.risk_level for r in results]
    n = len(results)

    per_level = tuple(_precision_recall_f1(predicted, gold, level) for level in _LEVELS)
    macro_f1 = sum(m.f1 for m in per_level) / len(per_level)
    high_metrics = next(m for m in per_level if m.level == RiskLevel.HIGH)

    gold_risky = [g in _RISKY_LEVELS for g in gold]
    pred_risky = [p in _RISKY_LEVELS for p in predicted]

    fp_count = sum(1 for gr, pr in zip(gold_risky, pred_risky, strict=True) if not gr and pr)
    safe_gold_count = sum(1 for gr in gold_risky if not gr)
    false_positive_rate = fp_count / safe_gold_count if safe_gold_count > 0 else 0.0

    fn_count = sum(1 for gr, pr in zip(gold_risky, pred_risky, strict=True) if gr and not pr)
    risky_gold_count = sum(1 for gr in gold_risky if gr)
    false_negative_rate = fn_count / risky_gold_count if risky_gold_count > 0 else 0.0

    abstention_rate = sum(1 for r in results if r.abstained) / n

    high_medium_results = [r for r in results if r.risk_level in _RISKY_LEVELS]
    if high_medium_results:
        with_evidence = sum(1 for r in high_medium_results if len(r.evidence.verified) > 0)
        high_medium_evidence_rate = with_evidence / len(high_medium_results)
    else:
        high_medium_evidence_rate = 0.0

    evidence_failure_rate = sum(1 for r in results if r.evidence.unverifiable_count > 0) / n
    signal_disagreement_rate = (
        sum(1 for r in results if r.signals.signal_agreement < _DISAGREEMENT_THRESHOLD) / n
    )

    if gold_category is not None:
        predicted_category = [r.risk_category for r in results]
        # Union of gold and predicted (not gold alone) — a category the
        # engine over-predicts but that never appears in gold would
        # otherwise have its precision silently unreported.
        present_categories = sorted(
            {c for c in (*gold_category, *predicted_category) if c is not None}, key=lambda c: c.value
        )
        per_category = tuple(
            _category_precision_recall_f1(predicted_category, gold_category, category)
            for category in present_categories
        )
    else:
        per_category = ()

    return RiskEvalReport(
        case_count=n,
        per_level=per_level,
        per_category=per_category,
        macro_f1=macro_f1,
        high_risk_precision=high_metrics.precision,
        high_risk_recall=high_metrics.recall,
        false_positive_rate=false_positive_rate,
        false_negative_rate=false_negative_rate,
        abstention_rate=abstention_rate,
        high_medium_with_verified_evidence_rate=high_medium_evidence_rate,
        evidence_failure_rate=evidence_failure_rate,
        signal_disagreement_rate=signal_disagreement_rate,
    )
