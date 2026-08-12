#!/usr/bin/env python
"""Risk Engine evaluation harness — Dataset_and_Evaluation_Spec.md SS5
("Classification (Risk Engine output)"), Phase 5 spec SS20-24.

Runs `risk_engine.score_clause()` against the synthetic benchmark
(backend/tests/fixtures/risk_engine_benchmark.py) and reports precision/
recall/F1 per risk level, macro F1, high-risk precision/recall, false
positive/negative rates, abstention rate, and the evidence/signal-agreement
diagnostics from Phase 5 spec SS24.

IMPORTANT — READ BEFORE CITING THESE NUMBERS:
This benchmark is synthetic and hand-authored for development/regression
purposes — NOT the real-world benchmark Dataset_and_Evaluation_Spec.md SS4
requires (independently annotated real documents, messy/scanned sources,
inter-annotator agreement). These numbers demonstrate the harness and engine
wiring work correctly and give a directional sanity check against known
structural patterns; they say nothing about production accuracy on real,
messy financial contracts. Do not report these numbers as production
accuracy.

Usage: (from backend/, so `app` and `tests` are importable)
    python ../corpus/eval/run_risk_engine_eval.py
"""

from __future__ import annotations

import sys
from pathlib import Path

_BACKEND_DIR = Path(__file__).resolve().parents[2] / "backend"
sys.path.insert(0, str(_BACKEND_DIR))

from app.models.enums import RiskLevel  # noqa: E402
from app.services.condition_extraction_service import extract_condition  # noqa: E402
from app.services.entity_extraction_service import extract_financial_entities  # noqa: E402
from app.services.risk_engine import EntitySignal, score_clause  # noqa: E402
from app.services.risk_engine_metrics import evaluate_risk_engine  # noqa: E402
from tests.fixtures.risk_engine_benchmark import BENCHMARK_CASES  # noqa: E402


def main() -> int:
    if not BENCHMARK_CASES:
        print("No benchmark cases found - nothing to evaluate.")
        return 1

    print(f"Risk Engine evaluation - {len(BENCHMARK_CASES)} synthetic benchmark cases")
    print("=" * 88)
    print(f"{'case':47s} {'predicted':10s} {'gold':10s} {'score':>6s} {'conf':>6s}")
    print("-" * 88)

    results = []
    gold: list[RiskLevel] = []
    for case in BENCHMARK_CASES:
        entities = extract_financial_entities(case.text)
        condition = extract_condition(case.text)
        entity_signals = [
            EntitySignal(e.entity_type, e.value, e.raw_text, e.start_char, e.end_char) for e in entities
        ]
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
        )
        results.append(result)
        gold.append(RiskLevel(case.gold_risk_level))

        marker = "  " if result.risk_level.value == case.gold_risk_level else "**"
        print(
            f"{marker}{case.name:45s} {result.risk_level.value:10s} {case.gold_risk_level:10s} "
            f"{result.risk_score:6.3f} {result.confidence_score:6.3f}"
        )

    report = evaluate_risk_engine(results, gold)

    print("-" * 88)
    print()
    print("Per-level precision / recall / F1:")
    for m in report.per_level:
        print(f"  {m.level.value:10s} P={m.precision:.2f} R={m.recall:.2f} F1={m.f1:.2f} (support={m.support})")
    print()
    print(f"Macro F1:                                  {report.macro_f1:.2f}")
    print(f"High-risk precision:                       {report.high_risk_precision:.2f}")
    print(f"High-risk recall:                          {report.high_risk_recall:.2f}")
    print(f"False-positive rate (safe flagged risky):  {report.false_positive_rate:.2%}")
    print(f"False-negative rate (risky flagged safe):  {report.false_negative_rate:.2%}")
    print(f"Abstention (UNKNOWN) rate:                 {report.abstention_rate:.2%}")
    print(f"HIGH/MEDIUM with verified evidence:         {report.high_medium_with_verified_evidence_rate:.2%}")
    print(f"Evidence failure rate (any unverifiable):  {report.evidence_failure_rate:.2%}")
    print(f"Signal disagreement rate:                  {report.signal_disagreement_rate:.2%}")
    print()
    print(
        "NOTE: synthetic benchmark only - not production accuracy. "
        "See Dataset_and_Evaluation_Spec.md SS4 for the real-world benchmark this does not replace."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
