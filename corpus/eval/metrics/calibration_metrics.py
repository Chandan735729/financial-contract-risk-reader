"""Confidence calibration metrics — Dataset_and_Evaluation_Spec.md SS6,
Phase 6 spec SS11.

`risk_engine.py`'s `confidence_score` is explicitly a documented heuristic,
**not yet calibrated** (docs/PROVISIONAL_DECISIONS.md P5.2). This module
provides the measurement + fitting machinery Dataset_and_Evaluation_Spec.md
SS6 requires so that claim can eventually change honestly, backed by
numbers — it does not itself claim the current confidence is calibrated.

**Fit only on DEV, never on TEST** (Phase 6 spec SS11: "Do not calibrate on
the held-out test set") — `fit_isotonic_calibration` takes exactly the
samples the caller passes it; callers are responsible for never passing
TEST-split samples into the fit step (see `run_calibration_eval.py`).

Isotonic regression here is a from-scratch pool-adjacent-violators (PAV)
implementation, not `sklearn.isotonic.IsotonicRegression` — scikit-learn is
not a declared backend dependency (only transitively installed via other
packages), and Phase 6 spec SS11 explicitly says "Do NOT add a complex ML
model unnecessarily." PAV is ~20 lines and exactly what isotonic regression
is defined to compute.
"""

from __future__ import annotations

from dataclasses import dataclass

# ==================================================================
# Reliability bins / ECE
# ==================================================================


@dataclass(frozen=True, slots=True)
class CalibrationBin:
    bin_lower: float
    bin_upper: float
    count: int
    mean_confidence: float
    empirical_accuracy: float


@dataclass(frozen=True, slots=True)
class ReliabilityReport:
    bins: tuple[CalibrationBin, ...]
    ece: float  # Expected Calibration Error
    sample_count: int


def compute_reliability(
    confidences: list[float], correct: list[bool], *, n_bins: int = 10
) -> ReliabilityReport:
    """`confidences[i]` is the model's confidence for sample `i`;
    `correct[i]` is whether that sample's prediction was actually correct.
    Bins are fixed-width over `[0, 1]` (the standard ECE construction)."""
    if len(confidences) != len(correct):
        raise ValueError("confidences and correct must be the same length")
    n = len(confidences)
    if n == 0:
        return ReliabilityReport(bins=(), ece=0.0, sample_count=0)

    bin_width = 1.0 / n_bins
    bins: list[CalibrationBin] = []
    ece = 0.0

    for i in range(n_bins):
        lower = i * bin_width
        upper = 1.0 if i == n_bins - 1 else (i + 1) * bin_width
        in_bin = [
            (c, ok)
            for c, ok in zip(confidences, correct, strict=True)
            if (lower <= c < upper) or (i == n_bins - 1 and c == 1.0)
        ]
        count = len(in_bin)
        if count == 0:
            bins.append(CalibrationBin(lower, upper, 0, 0.0, 0.0))
            continue
        mean_conf = sum(c for c, _ in in_bin) / count
        accuracy = sum(1 for _, ok in in_bin if ok) / count
        bins.append(CalibrationBin(lower, upper, count, mean_conf, accuracy))
        ece += (count / n) * abs(mean_conf - accuracy)

    return ReliabilityReport(bins=tuple(bins), ece=ece, sample_count=n)


@dataclass(frozen=True, slots=True)
class CalibrationBreakdown:
    key: str
    ece: float
    sample_count: int


def ece_by_group(
    confidences: list[float], correct: list[bool], groups: list[str], *, n_bins: int = 10
) -> tuple[CalibrationBreakdown, ...]:
    """ECE computed separately per group value (e.g. per `risk_level` or per
    `risk_category`) — Phase 6 spec SS11: "calibration error by risk level
    ... by category"."""
    if not (len(confidences) == len(correct) == len(groups)):
        raise ValueError("confidences, correct, and groups must be the same length")
    by_group: dict[str, tuple[list[float], list[bool]]] = {}
    for c, ok, g in zip(confidences, correct, groups, strict=True):
        conf_list, correct_list = by_group.setdefault(g, ([], []))
        conf_list.append(c)
        correct_list.append(ok)

    results = []
    for group, (conf_list, correct_list) in sorted(by_group.items()):
        report = compute_reliability(conf_list, correct_list, n_bins=n_bins)
        results.append(CalibrationBreakdown(key=group, ece=report.ece, sample_count=report.sample_count))
    return tuple(results)


# ==================================================================
# Isotonic calibration fit (pool-adjacent-violators)
# ==================================================================


@dataclass(frozen=True, slots=True)
class IsotonicCalibrationModel:
    """A monotonic step function fit by PAV: `x_thresholds[i]` maps to
    `y_values[i]`; `predict()` interpolates linearly between the nearest
    fitted points (flat extrapolation at the ends)."""

    x_thresholds: tuple[float, ...]
    y_values: tuple[float, ...]

    def predict(self, x: float) -> float:
        if not self.x_thresholds:
            return x
        if x <= self.x_thresholds[0]:
            return self.y_values[0]
        if x >= self.x_thresholds[-1]:
            return self.y_values[-1]
        for i in range(len(self.x_thresholds) - 1):
            x0, x1 = self.x_thresholds[i], self.x_thresholds[i + 1]
            if x0 <= x <= x1:
                y0, y1 = self.y_values[i], self.y_values[i + 1]
                if x1 == x0:
                    return y0
                t = (x - x0) / (x1 - x0)
                return y0 + t * (y1 - y0)
        return self.y_values[-1]


def fit_isotonic_calibration(confidences: list[float], correct: list[bool]) -> IsotonicCalibrationModel:
    """Pool-adjacent-violators algorithm: fits the monotonic non-decreasing
    step function minimizing squared error against `correct` (as 0/1),
    ordered by `confidences`. Standard isotonic regression — see e.g.
    Robertson, Wright & Dykstra (1988). Only ever call this with DEV-split
    samples (module docstring)."""
    if len(confidences) != len(correct):
        raise ValueError("confidences and correct must be the same length")
    if not confidences:
        return IsotonicCalibrationModel(x_thresholds=(), y_values=())

    order = sorted(range(len(confidences)), key=lambda i: confidences[i])
    xs = [confidences[i] for i in order]
    ys = [1.0 if correct[i] else 0.0 for i in order]

    # Each "block" starts as a single point; adjacent blocks whose means
    # violate monotonicity (later block's mean < earlier block's mean) are
    # merged (pooled) until the whole sequence is non-decreasing.
    block_sums = list(ys)
    block_weights = [1.0] * len(ys)
    block_x_start = list(range(len(ys)))

    i = 0
    while i < len(block_sums) - 1:
        mean_i = block_sums[i] / block_weights[i]
        mean_next = block_sums[i + 1] / block_weights[i + 1]
        if mean_i > mean_next:
            block_sums[i] += block_sums[i + 1]
            block_weights[i] += block_weights[i + 1]
            del block_sums[i + 1]
            del block_weights[i + 1]
            del block_x_start[i + 1]
            if i > 0:
                i -= 1
        else:
            i += 1

    # One representative x per pooled block (mean of its member x's) paired
    # with that block's pooled mean y.
    thresholds: list[float] = []
    values: list[float] = []
    start = 0
    for w in block_weights:
        count = int(round(w))
        block_xs = xs[start : start + count]
        thresholds.append(sum(block_xs) / len(block_xs))
        start += count
    values = [s / w for s, w in zip(block_sums, block_weights, strict=True)]

    return IsotonicCalibrationModel(x_thresholds=tuple(thresholds), y_values=tuple(values))
