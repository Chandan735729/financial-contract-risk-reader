#!/usr/bin/env python
"""Confidence calibration evaluation — Dataset_and_Evaluation_Spec.md SS6,
Phase 6 spec SS11-12.

Builds reliability bins + ECE from every DEV/TEST risk-classification case,
fits an isotonic calibration mapping **on DEV only**, evaluates ECE on both
splits, and prints the HIGH x confidence cross-tabulation Phase 6 spec SS12
asks for.

**Do not read this as a calibrated system.** `risk_engine.py`'s
`confidence_score` remains an explicit, documented heuristic
(docs/PROVISIONAL_DECISIONS.md P5.2) — this script measures how far from
calibrated it currently is and demonstrates the fitting machinery, it does
not flip that status. The sample size here (well under 50) is far too
small for a statistically meaningful ECE — stated explicitly, not
glossed over (Phase 6 spec: "Do not manufacture statistical confidence").

Usage: (from backend/, so `app` and `tests` are importable)
    python ../corpus/eval/run_calibration_eval.py
"""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_BACKEND_DIR = _REPO_ROOT / "backend"
for _path in (str(_REPO_ROOT), str(_BACKEND_DIR)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from app.models.enums import RiskLevel  # noqa: E402
from app.services.condition_extraction_service import extract_condition  # noqa: E402
from app.services.entity_extraction_service import extract_financial_entities  # noqa: E402
from app.services.risk_engine import EntitySignal, score_clause  # noqa: E402
from corpus.eval.datasets.risk_test_holdout import RISK_TEST_HOLDOUT  # noqa: E402
from corpus.eval.metrics.calibration_metrics import (  # noqa: E402
    compute_reliability,
    ece_by_group,
    fit_isotonic_calibration,
)
from tests.fixtures.risk_engine_benchmark import BENCHMARK_CASES as DEV_RISK_CASES  # noqa: E402


def _score(text: str, *, matched_patterns=None, document_type, low_confidence_flag=False):
    entities = extract_financial_entities(text)
    condition = extract_condition(text)
    entity_signals = [
        EntitySignal(e.entity_type, e.value, e.raw_text, e.start_char, e.end_char) for e in entities
    ]
    return score_clause(
        text,
        matched_patterns=matched_patterns or [],
        entities=entity_signals,
        trigger=condition.trigger,
        condition_text=condition.condition,
        consequence=condition.consequence,
        document_type=document_type,
        clause_low_confidence_flag=low_confidence_flag,
        page_number=1,
    )


def _print_reliability(label: str, confidences: list[float], correct: list[bool]) -> None:
    report = compute_reliability(confidences, correct, n_bins=5)
    print(f"\n-- {label} (n={report.sample_count}) --")
    print(f"  ECE: {report.ece:.3f}")
    for b in report.bins:
        if b.count == 0:
            continue
        print(
            f"    [{b.bin_lower:.1f}-{b.bin_upper:.1f}) n={b.count:2d} "
            f"mean_confidence={b.mean_confidence:.2f} empirical_accuracy={b.empirical_accuracy:.2f}"
        )


def main() -> int:
    dev_confidences: list[float] = []
    dev_correct: list[bool] = []
    dev_levels: list[str] = []

    test_confidences: list[float] = []
    test_correct: list[bool] = []
    test_levels: list[str] = []

    cross_tab: dict[tuple[str, str], list[str]] = {}

    for case in DEV_RISK_CASES:
        result = _score(case.text, document_type=case.document_type)
        gold = RiskLevel(case.gold_risk_level)
        is_correct = result.risk_level == gold
        dev_confidences.append(result.confidence_score)
        dev_correct.append(is_correct)
        dev_levels.append(result.risk_level.value)
        cross_tab.setdefault((result.risk_level.value, result.confidence_level.value), []).append(case.name)

    for test_case in RISK_TEST_HOLDOUT:
        # RISK_TEST_HOLDOUT cases deliberately carry no retrieval matches
        # (the reference corpus is empty in production today — see that
        # module's docstring), so matched_patterns is omitted (defaults to []).
        result = _score(
            test_case.text,
            document_type=test_case.document_type,
            low_confidence_flag=test_case.low_confidence_flag,
        )
        is_correct = result.risk_level == test_case.risk_level
        test_confidences.append(result.confidence_score)
        test_correct.append(is_correct)
        test_levels.append(result.risk_level.value)
        cross_tab.setdefault((result.risk_level.value, result.confidence_level.value), []).append(
            test_case.case_id
        )

    print("Confidence calibration evaluation")
    print("=" * 78)
    print(f"WARNING: sample sizes (DEV n={len(dev_confidences)}, TEST n={len(test_confidences)}) are far too")
    print("small for a statistically meaningful calibration curve. Numbers below are diagnostic")
    print("only - see docs/PROVISIONAL_DECISIONS.md and the module docstring.")

    _print_reliability("DEV reliability", dev_confidences, dev_correct)
    _print_reliability("TEST reliability", test_confidences, test_correct)

    print("\n-- ECE by predicted risk_level (DEV) --")
    for b in ece_by_group(dev_confidences, dev_correct, dev_levels, n_bins=5):
        print(f"    {b.key:10s} ECE={b.ece:.3f} (n={b.sample_count})")

    print("\n-- Isotonic calibration fit on DEV only (never on TEST) --")
    model = fit_isotonic_calibration(dev_confidences, dev_correct)
    print(f"  fitted breakpoints: {[round(x, 2) for x in model.x_thresholds]}")
    print(f"  fitted calibrated values: {[round(y, 2) for y in model.y_values]}")

    if test_confidences:
        calibrated_test = [model.predict(c) for c in test_confidences]
        recalibrated_report = compute_reliability(calibrated_test, test_correct, n_bins=5)
        raw_report = compute_reliability(test_confidences, test_correct, n_bins=5)
        print("\n-- Effect of DEV-fitted calibration when applied to TEST --")
        print(f"  raw ECE on TEST:          {raw_report.ece:.3f}")
        print(f"  DEV-calibrated ECE on TEST: {recalibrated_report.ece:.3f}")

    print("\n-- Risk level x confidence level cross-tabulation (Phase 6 spec SS12) --")
    for risk_level in ("HIGH", "MEDIUM", "LOW", "UNKNOWN"):
        for confidence_level in ("HIGH", "MEDIUM", "LOW"):
            cases = cross_tab.get((risk_level, confidence_level), [])
            if cases:
                print(
                    f"  {risk_level:8s} + {confidence_level:6s} confidence: n={len(cases)}  e.g. {cases[:3]}"
                )

    print()
    print(
        "NOTE: confidence_score is an explicit heuristic, not a calibrated probability "
        "(docs/PROVISIONAL_DECISIONS.md P5.2). This script measures the current gap; it "
        "does not certify calibration. Never fit on the TEST split."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
