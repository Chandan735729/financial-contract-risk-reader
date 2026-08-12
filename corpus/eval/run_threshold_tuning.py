#!/usr/bin/env python
"""Threshold/weight tuning process — Phase 6 spec SS13.

Evaluates a small grid of candidate `RiskEngineConfig` threshold variations
against the **DEV split only** (`backend/tests/fixtures/risk_engine_benchmark.py`)
and ranks them **lexicographically** — HIGH precision, then HIGH recall,
then macro F1, then abstention-rate reasonableness, then a lower
signal-disagreement rate as a crude calibration-adjacent tiebreaker — never
collapsed into one blended scalar (Phase 6 spec SS13: "Do not optimize
everything against one scalar score unless there is a clearly justified
reason").

**This script reports; it does not apply.** It never writes to
`risk_engine_config.py` — selecting a new default is a deliberate, reviewed
code change, not something a tuning script should do unattended (Phase 6
spec SS13: "Do NOT modify them blindly"). It records which candidate wins
and whether that matches the already-shipped `risk_engine_v1` default.

**Never touches the TEST split** — `RISK_TEST_HOLDOUT` is not imported
here.

Usage: (from backend/, so `app` and `tests` are importable)
    python ../corpus/eval/run_threshold_tuning.py
"""

from __future__ import annotations

import sys
from dataclasses import replace
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
from app.services.risk_engine_config import DEFAULT_RISK_ENGINE_CONFIG, RiskEngineConfig  # noqa: E402
from app.services.risk_engine_metrics import RiskEvalReport, evaluate_risk_engine  # noqa: E402
from tests.fixtures.risk_engine_benchmark import BENCHMARK_CASES as DEV_CASES  # noqa: E402

# A "reasonable" abstention rate is treated as closeness to the current
# default's own DEV abstention rate, not a fixed target — abstention should
# be judged for *correctness* (Phase 6 spec SS10), not driven toward a
# number by threshold tuning. This grid search only ranks candidates that
# do not push abstention far from that baseline.
_ABSTENTION_TOLERANCE = 0.15


def _prepare_cases() -> list:
    prepared = []
    for case in DEV_CASES:
        entities = extract_financial_entities(case.text)
        condition = extract_condition(case.text)
        entity_signals = [
            EntitySignal(e.entity_type, e.value, e.raw_text, e.start_char, e.end_char) for e in entities
        ]
        prepared.append((case, entity_signals, condition))
    return prepared


def _evaluate_config(config: RiskEngineConfig, prepared: list) -> RiskEvalReport:
    results = []
    gold: list[RiskLevel] = []
    for case, entity_signals, condition in prepared:
        result = score_clause(
            case.text,
            matched_patterns=list(case.matched_patterns),
            entities=entity_signals,
            trigger=condition.trigger,
            condition_text=condition.condition,
            consequence=condition.consequence,
            document_type=case.document_type,
            clause_low_confidence_flag=case.low_confidence_flag,
            page_number=1,
            config=config,
        )
        results.append(result)
        gold.append(RiskLevel(case.gold_risk_level))
    return evaluate_risk_engine(results, gold)


def build_candidate_grid(base: RiskEngineConfig) -> list[tuple[str, RiskEngineConfig]]:
    candidates: list[tuple[str, RiskEngineConfig]] = [("current_default (risk_engine_v1)", base)]
    for high in (0.65, 0.70, 0.75):
        for medium in (0.40, 0.45, 0.50):
            if not (high > medium > base.low_threshold):
                continue
            for floor in (0.40, 0.50, 0.60):
                if (
                    high == base.high_threshold
                    and medium == base.medium_threshold
                    and floor == base.confidence_floor
                ):
                    continue  # already covered by "current_default"
                name = f"high={high:.2f},medium={medium:.2f},floor={floor:.2f}"
                candidates.append(
                    (
                        name,
                        replace(base, high_threshold=high, medium_threshold=medium, confidence_floor=floor),
                    )
                )
    return candidates


def main() -> int:
    print(f"Threshold tuning - {len(DEV_CASES)} DEV cases, grid search over threshold/floor candidates")
    print("=" * 100)
    print(
        "Priority order (lexicographic, never a single blended score): HIGH precision > HIGH recall > macro F1"
    )
    print(
        f"> abstention-rate closeness to baseline (tolerance={_ABSTENTION_TOLERANCE}) > lower signal disagreement.\n"
    )

    prepared = _prepare_cases()
    baseline_report = _evaluate_config(DEFAULT_RISK_ENGINE_CONFIG, prepared)
    baseline_abstention = baseline_report.abstention_rate

    candidates = build_candidate_grid(DEFAULT_RISK_ENGINE_CONFIG)
    scored: list[tuple[tuple, str, RiskEngineConfig]] = []

    for name, config in candidates:
        report = _evaluate_config(config, prepared)
        abstention_penalty = abs(report.abstention_rate - baseline_abstention) <= _ABSTENTION_TOLERANCE
        rank_key = (
            round(report.high_risk_precision, 4),
            round(report.high_risk_recall, 4),
            round(report.macro_f1, 4),
            1 if abstention_penalty else 0,
            round(-report.signal_disagreement_rate, 4),
        )
        scored.append((rank_key, name, config))

    scored.sort(key=lambda item: item[0], reverse=True)

    print(f"{'candidate':45s} {'HIGH-P':>7s} {'HIGH-R':>7s} {'macroF1':>8s} {'abst':>6s}")
    print("-" * 100)
    for rank_key, name, config in scored[:10]:
        report = _evaluate_config(config, prepared)
        marker = " <-- top-ranked" if (rank_key, name, config) == scored[0] else ""
        print(
            f"{name:45s} {report.high_risk_precision:7.2f} {report.high_risk_recall:7.2f} "
            f"{report.macro_f1:8.2f} {report.abstention_rate:6.2%}{marker}"
        )

    winner_name = scored[0][1]
    winner_config = scored[0][2]
    print(f"\nTop-ranked candidate: {winner_name}")
    if winner_config == DEFAULT_RISK_ENGINE_CONFIG:
        print("This matches the currently shipped risk_engine_v1 default exactly.")
    else:
        print(
            "This differs from the currently shipped risk_engine_v1 default. "
            "NOT applied automatically - a threshold change is a deliberate, reviewed "
            "code change (Phase 6 spec SS13), and any such change must be re-validated "
            "against the eval harness and, before shipping, checked it does not merely "
            "overfit this small DEV set."
        )

    print()
    print(
        "NOTE: DEV split only (n=15) - this grid search result is a development-time "
        "signal, not a statistically robust threshold selection. Never evaluated against "
        "or fit on the TEST split."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
