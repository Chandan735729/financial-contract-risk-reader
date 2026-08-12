#!/usr/bin/env python
"""Risk Engine evaluation harness — Dataset_and_Evaluation_Spec.md SS5
("Classification (Risk Engine output)"), Phase 5 spec SS20-24, **Phase 6
spec SS1/SS9/SS13** (DEV/TEST split separation, adversarial cases A-I).

Runs `risk_engine.score_clause()` against three non-overlapping case groups:

1. **DEV** (`backend/tests/fixtures/risk_engine_benchmark.py`) — the set
   `risk_engine_v1`'s weights/thresholds were tuned against (Phase 5).
2. **TEST** (`corpus/eval/datasets/risk_test_holdout.py`) — held out, never
   used for tuning; see that module's docstring for the honesty caveat on
   how "held-out" this really is.
3. **ADVERSARIAL** (`corpus/eval/datasets/adversarial_risk_cases.py`) —
   Phase 6 spec SS9's cases A-I, scored pass/fail/known-gap against each
   case's own `expected_levels`/`forbidden_levels`/`strict` semantics
   (several of the spec's own case descriptions are hedged, not a single
   fixed label — see that module's docstring).

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
from dataclasses import dataclass
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_BACKEND_DIR = _REPO_ROOT / "backend"
for _path in (str(_REPO_ROOT), str(_BACKEND_DIR)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from app.models.enums import RiskLevel  # noqa: E402
from app.services.condition_extraction_service import extract_condition  # noqa: E402
from app.services.entity_extraction_service import extract_financial_entities  # noqa: E402
from app.services.risk_engine import EntitySignal, RiskResult, score_clause  # noqa: E402
from app.services.risk_engine_metrics import evaluate_risk_engine  # noqa: E402
from corpus.eval.datasets.adversarial_risk_cases import ADVERSARIAL_CASES  # noqa: E402
from corpus.eval.datasets.risk_test_holdout import RISK_TEST_HOLDOUT  # noqa: E402
from tests.fixtures.risk_engine_benchmark import BENCHMARK_CASES as DEV_CASES  # noqa: E402


@dataclass(frozen=True, slots=True)
class _NormalizedCase:
    """Common shape `_run_dev_or_test` scores against — `DEV_CASES`
    (`RiskBenchmarkCase`) and `RISK_TEST_HOLDOUT` (`ClauseGroundTruth`) use
    different field names/types (`name` vs. `case_id`, `gold_risk_level` as
    a string vs. `risk_level` as a `RiskLevel`), so each is adapted into
    this shape before scoring rather than special-cased inline."""

    name: str
    text: str
    gold_risk_level: str
    document_type: object
    matched_patterns: tuple
    low_confidence_flag: bool
    known_gap: bool = False


def _from_dev_case(case) -> _NormalizedCase:
    return _NormalizedCase(
        name=case.name,
        text=case.text,
        gold_risk_level=case.gold_risk_level,
        document_type=case.document_type,
        matched_patterns=tuple(case.matched_patterns),
        low_confidence_flag=case.low_confidence_flag,
    )


def _from_ground_truth(case) -> _NormalizedCase:
    return _NormalizedCase(
        name=case.case_id,
        text=case.text,
        gold_risk_level=case.risk_level.value,
        document_type=case.document_type,
        matched_patterns=(),
        low_confidence_flag=case.low_confidence_flag,
        known_gap=case.known_gap,
    )


def _score_text(text: str, *, matched_patterns, document_type, low_confidence_flag) -> RiskResult:
    entities = extract_financial_entities(text)
    condition = extract_condition(text)
    entity_signals = [
        EntitySignal(e.entity_type, e.value, e.raw_text, e.start_char, e.end_char) for e in entities
    ]
    return score_clause(
        text,
        matched_patterns=list(matched_patterns),
        entities=entity_signals,
        trigger=condition.trigger,
        condition_text=condition.condition,
        consequence=condition.consequence,
        document_type=document_type,
        clause_low_confidence_flag=low_confidence_flag,
        page_number=1,
    )


def _print_report(results: list[RiskResult], gold: list[RiskLevel]) -> None:
    report = evaluate_risk_engine(results, gold)
    print("\nPer-level precision / recall / F1:")
    for m in report.per_level:
        print(
            f"  {m.level.value:10s} P={m.precision:.2f} R={m.recall:.2f} F1={m.f1:.2f} (support={m.support})"
        )
    print(f"\nMacro F1:                                  {report.macro_f1:.2f}")
    print(f"High-risk precision:                       {report.high_risk_precision:.2f}")
    print(f"High-risk recall:                          {report.high_risk_recall:.2f}")
    print(f"False-positive rate (safe flagged risky):  {report.false_positive_rate:.2%}")
    print(f"False-negative rate (risky flagged safe):  {report.false_negative_rate:.2%}")
    print(f"Abstention (UNKNOWN) rate:                 {report.abstention_rate:.2%}")
    print(f"HIGH/MEDIUM with verified evidence:         {report.high_medium_with_verified_evidence_rate:.2%}")
    print(f"Evidence failure rate (any unverifiable):  {report.evidence_failure_rate:.2%}")
    print(f"Signal disagreement rate:                  {report.signal_disagreement_rate:.2%}")


def _run_dev_or_test(label: str, cases: list[_NormalizedCase]) -> None:
    print(f"\n{'=' * 88}\n{label} split - {len(cases)} cases\n{'=' * 88}")
    print(f"{'case':47s} {'predicted':10s} {'gold':10s} {'score':>6s} {'conf':>6s} {'gap':>5s}")
    print("-" * 88)

    results: list[RiskResult] = []
    gold: list[RiskLevel] = []
    for case in cases:
        result = _score_text(
            case.text,
            matched_patterns=case.matched_patterns,
            document_type=case.document_type,
            low_confidence_flag=case.low_confidence_flag,
        )
        results.append(result)
        gold_level = RiskLevel(case.gold_risk_level)
        gold.append(gold_level)

        matched = result.risk_level == gold_level
        gap_tag = "GAP" if (not matched and case.known_gap) else ""
        marker = "  " if matched else "**"
        print(
            f"{marker}{case.name:45s} {result.risk_level.value:10s} {case.gold_risk_level:10s} "
            f"{result.risk_score:6.3f} {result.confidence_score:6.3f} {gap_tag:>5s}"
        )

    _print_report(results, gold)


def _run_adversarial() -> None:
    print(f"\n{'=' * 88}\nADVERSARIAL split - {len(ADVERSARIAL_CASES)} cases (Phase 6 spec SS9)\n{'=' * 88}")
    passed = failed = known_gaps = soft_findings = 0

    for case in ADVERSARIAL_CASES:
        result = _score_text(
            case.text,
            matched_patterns=case.matched_patterns,
            document_type=case.document_type,
            low_confidence_flag=case.low_confidence_flag,
        )
        ok = True
        if case.expected_levels is not None:
            ok = ok and (result.risk_level in case.expected_levels)
        if case.forbidden_levels:
            ok = ok and (result.risk_level not in case.forbidden_levels)

        if case.expected_levels is None and not case.forbidden_levels:
            status = "OBSERVE"
        elif ok:
            status = "PASS"
            passed += 1
        elif case.known_gap:
            status = "KNOWN-GAP"
            known_gaps += 1
        elif not case.strict:
            status = "SOFT-FAIL"
            soft_findings += 1
        else:
            status = "FAIL"
            failed += 1

        print(f"\n[{status}] Case {case.case_id}: {case.spec_expectation}")
        print(f"   text: {case.text!r}")
        print(
            f"   -> {result.risk_level.value} (score={result.risk_score:.3f}, "
            f"confidence={result.confidence_score:.3f})"
        )

    print(
        f"\nAdversarial summary: {passed} pass, {failed} fail (gate-relevant), "
        f"{known_gaps} known-gap (documented, not gated), {soft_findings} soft-fail (hedged spec wording)"
    )
    if failed > 0:
        print(f"WARNING: {failed} adversarial case(s) failed a *strict* expectation with no known-gap label.")


def main() -> int:
    print("Risk Engine evaluation (Phase 5 risk_engine_v1)")

    _run_dev_or_test("DEV", [_from_dev_case(c) for c in DEV_CASES])
    _run_dev_or_test("TEST (held-out)", [_from_ground_truth(c) for c in RISK_TEST_HOLDOUT])
    _run_adversarial()

    print(f"\n{'=' * 88}")
    print(
        "NOTE: all three splits above are synthetic and hand-authored - not production "
        "accuracy. See Dataset_and_Evaluation_Spec.md SS4 for the real-world benchmark this "
        "does not replace, and corpus/eval/datasets/risk_test_holdout.py's docstring for why "
        "the TEST split is not a genuinely blind evaluation."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
