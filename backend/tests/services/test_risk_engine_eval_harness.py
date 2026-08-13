"""Risk Engine evaluation harness self-correctness tests — Phase 5 spec
SS21/SS24 ("the harness's own correctness").

`test_risk_engine_metrics.py`-equivalent arithmetic checks live inline here
(hand-computed known answers) plus an end-to-end run of the synthetic
benchmark (tests/fixtures/risk_engine_benchmark.py) as a regression guard —
not a production-accuracy claim. See the benchmark module's docstring and
corpus/eval/run_risk_engine_eval.py.
"""

from __future__ import annotations

import pytest

from app.models.enums import ConfidenceLevel, RiskCategory, RiskLevel
from app.services.condition_extraction_service import extract_condition
from app.services.entity_extraction_service import extract_financial_entities
from app.services.evidence_engine import EvidenceResult
from app.services.risk_engine import EntitySignal, RiskResult, RiskSignals, score_clause
from app.services.risk_engine_metrics import evaluate_risk_engine
from tests.fixtures.risk_engine_benchmark import BENCHMARK_CASES


def _dummy_signals() -> RiskSignals:
    return RiskSignals(
        dense_similarity=0.0,
        lexical_score=0.0,
        entity_strength=0.0,
        condition_completeness_score=0.0,
        condition_completeness_label="none",
        rule_hit=False,
        rule_boost=0.0,
        rule_matches=(),
        candidate_category=None,
        candidate_subcategory=None,
        doc_type_relevance=1.0,
        retrieval_margin=0.0,
        signal_agreement=0.0,
        corroboration=0.0,
        has_positive_low_evidence=False,
    )


def _dummy_evidence() -> EvidenceResult:
    return EvidenceResult(verified=(), unverifiable_count=0, diagnostics=())


def _make_result(
    level: RiskLevel, *, abstained: bool = False, category: RiskCategory | None = None
) -> RiskResult:
    return RiskResult(
        risk_level=level,
        risk_score=0.0,
        risk_category=category,
        risk_subcategory=None,
        confidence_level=ConfidenceLevel.LOW,
        confidence_score=0.0,
        abstained=abstained,
        abstain_reason="x" if abstained else None,
        engine_version="test",
        signals=_dummy_signals(),
        evidence=_dummy_evidence(),
    )


def _run_case(case) -> RiskResult:
    entities = extract_financial_entities(case.text)
    condition = extract_condition(case.text)
    entity_signals = [
        EntitySignal(e.entity_type, e.value, e.raw_text, e.start_char, e.end_char) for e in entities
    ]
    return score_clause(
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


class TestMetricsArithmetic:
    """Hand-computed known answers, independent of the benchmark fixture."""

    def test_perfect_predictions_yield_precision_recall_f1_of_one(self):
        results = [
            _make_result(level, abstained=level == RiskLevel.UNKNOWN)
            for level in (RiskLevel.HIGH, RiskLevel.MEDIUM, RiskLevel.LOW, RiskLevel.UNKNOWN)
        ]
        gold = [RiskLevel.HIGH, RiskLevel.MEDIUM, RiskLevel.LOW, RiskLevel.UNKNOWN]
        report = evaluate_risk_engine(results, gold)
        assert report.macro_f1 == 1.0
        for m in report.per_level:
            assert m.precision == 1.0
            assert m.recall == 1.0
            assert m.f1 == 1.0

    def test_all_wrong_yields_zero_precision_and_recall_for_gold_classes(self):
        results = [
            _make_result(RiskLevel.LOW),
            _make_result(RiskLevel.LOW),
        ]
        gold = [RiskLevel.HIGH, RiskLevel.HIGH]
        report = evaluate_risk_engine(results, gold)
        high = next(m for m in report.per_level if m.level == RiskLevel.HIGH)
        low = next(m for m in report.per_level if m.level == RiskLevel.LOW)
        assert high.precision == 0.0
        assert high.recall == 0.0
        assert low.precision == 0.0  # predicted LOW but never correct
        assert low.recall == 0.0  # no gold LOW instances -> support 0 -> recall 0

    def test_false_positive_and_negative_rates_hand_computed(self):
        # 2 gold-risky (HIGH), 2 gold-safe (LOW). One risky predicted safe
        # (1 FN of 2 risky = 50%); one safe predicted risky (1 FP of 2 safe = 50%).
        results = [
            _make_result(RiskLevel.HIGH),  # correct
            _make_result(RiskLevel.LOW),  # FN: gold HIGH, predicted LOW
            _make_result(RiskLevel.LOW),  # correct
            _make_result(RiskLevel.MEDIUM),  # FP: gold LOW, predicted MEDIUM
        ]
        gold = [RiskLevel.HIGH, RiskLevel.HIGH, RiskLevel.LOW, RiskLevel.LOW]
        report = evaluate_risk_engine(results, gold)
        assert report.false_negative_rate == 0.5
        assert report.false_positive_rate == 0.5

    def test_abstention_rate_hand_computed(self):
        results = [_make_result(RiskLevel.UNKNOWN, abstained=True), _make_result(RiskLevel.HIGH)]
        gold = [RiskLevel.UNKNOWN, RiskLevel.HIGH]
        report = evaluate_risk_engine(results, gold)
        assert report.abstention_rate == 0.5

    def test_empty_input_does_not_crash(self):
        report = evaluate_risk_engine([], [])
        assert report.case_count == 0
        assert report.macro_f1 == 0.0
        assert report.per_category == ()


class TestPerCategoryMetrics:
    """PHASE_6.5: `per_category` breakdown alongside the existing
    per-`RiskLevel` one, so a report can show which taxonomy category
    improved, not just HIGH/MEDIUM/LOW/UNKNOWN in aggregate."""

    def test_omitting_gold_category_yields_empty_per_category(self):
        results = [_make_result(RiskLevel.HIGH, category=RiskCategory.FINANCIAL_COST)]
        report = evaluate_risk_engine(results, [RiskLevel.HIGH])
        assert report.per_category == ()

    def test_perfect_category_predictions_yield_precision_recall_f1_of_one(self):
        results = [
            _make_result(RiskLevel.HIGH, category=RiskCategory.FINANCIAL_COST),
            _make_result(RiskLevel.MEDIUM, category=RiskCategory.INSURANCE),
        ]
        gold = [RiskLevel.HIGH, RiskLevel.MEDIUM]
        gold_category: list[RiskCategory | None] = [RiskCategory.FINANCIAL_COST, RiskCategory.INSURANCE]
        report = evaluate_risk_engine(results, gold, gold_category=gold_category)
        assert {m.category for m in report.per_category} == {
            RiskCategory.FINANCIAL_COST,
            RiskCategory.INSURANCE,
        }
        for m in report.per_category:
            assert m.precision == 1.0
            assert m.recall == 1.0
            assert m.f1 == 1.0
            assert m.support == 1

    def test_wrong_category_lowers_precision_and_recall(self):
        # Gold FINANCIAL_COST, predicted INSURANCE — a miss for both categories.
        results = [_make_result(RiskLevel.HIGH, category=RiskCategory.INSURANCE)]
        gold = [RiskLevel.HIGH]
        gold_category: list[RiskCategory | None] = [RiskCategory.FINANCIAL_COST]
        report = evaluate_risk_engine(results, gold, gold_category=gold_category)
        financial = next(m for m in report.per_category if m.category == RiskCategory.FINANCIAL_COST)
        insurance = next(m for m in report.per_category if m.category == RiskCategory.INSURANCE)
        assert financial.recall == 0.0  # gold FINANCIAL_COST never predicted
        assert insurance.precision == 0.0  # predicted INSURANCE never correct

    def test_none_gold_category_never_counted_as_a_category(self):
        results = [_make_result(RiskLevel.UNKNOWN, category=None)]
        gold = [RiskLevel.UNKNOWN]
        report = evaluate_risk_engine(results, gold, gold_category=[None])
        assert report.per_category == ()

    def test_mismatched_gold_category_length_raises(self):
        results = [_make_result(RiskLevel.HIGH, category=RiskCategory.FINANCIAL_COST)]
        with pytest.raises(ValueError):
            evaluate_risk_engine(results, [RiskLevel.HIGH], gold_category=[])

    def test_mismatched_lengths_raise(self):
        with pytest.raises(ValueError):
            evaluate_risk_engine([_make_result(RiskLevel.HIGH)], [])


class TestSyntheticBenchmarkEndToEnd:
    def test_benchmark_has_cases_across_all_four_levels(self):
        levels = {case.gold_risk_level for case in BENCHMARK_CASES}
        assert levels == {"HIGH", "MEDIUM", "LOW", "UNKNOWN"}

    def test_every_benchmark_case_runs_without_crashing(self):
        for case in BENCHMARK_CASES:
            result = _run_case(case)
            assert result is not None

    def test_benchmark_predictions_match_gold_labels(self):
        # This benchmark is hand-authored so the engine's predicted level is
        # known-correct by construction (see fixture module docstring) — a
        # regression guard, not a production-accuracy claim.
        results = [_run_case(case) for case in BENCHMARK_CASES]
        mismatches = [
            (case.name, r.risk_level.value, case.gold_risk_level)
            for case, r in zip(BENCHMARK_CASES, results, strict=True)
            if r.risk_level.value != case.gold_risk_level
        ]
        assert mismatches == []

    def test_benchmark_macro_f1_is_perfect(self):
        results = [_run_case(case) for case in BENCHMARK_CASES]
        gold = [RiskLevel(case.gold_risk_level) for case in BENCHMARK_CASES]
        report = evaluate_risk_engine(results, gold)
        assert report.macro_f1 == 1.0

    def test_benchmark_high_medium_decisions_are_always_evidenced(self):
        results = [_run_case(case) for case in BENCHMARK_CASES]
        gold = [RiskLevel(case.gold_risk_level) for case in BENCHMARK_CASES]
        report = evaluate_risk_engine(results, gold)
        assert report.high_medium_with_verified_evidence_rate == 1.0
