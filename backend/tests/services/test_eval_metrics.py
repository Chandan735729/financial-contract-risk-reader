"""Evaluation-framework metric correctness tests — Phase 6 spec SS19
("The evaluation framework must not have metric bugs").

Hand-computed known-answer tests for every new `corpus/eval/metrics/*`
module. `Recall@K`/`MRR` and risk-classification P/R/F1 already have
dedicated known-answer coverage from Phase 4/5
(`test_retrieval_metrics.py`, `test_risk_engine_eval_harness.py`) and are
not duplicated here.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from corpus.eval.metrics.abstention_metrics import abstention_by_group, evaluate_abstention
from corpus.eval.metrics.calibration_metrics import (
    compute_reliability,
    ece_by_group,
    fit_isotonic_calibration,
)
from corpus.eval.metrics.condition_metrics import evaluate_conditions
from corpus.eval.metrics.entity_metrics import evaluate_entities
from corpus.eval.metrics.evidence_metrics import evaluate_evidence_clauses, evaluate_integrity_probes
from corpus.eval.schema import ClauseGroundTruth, DatasetSplit, GroundTruthEntity, GroundTruthEvidenceSpan


@dataclass(frozen=True, slots=True)
class _FakeEntity:
    entity_type: str
    raw_text: str
    value: str
    start_char: int
    end_char: int


class TestEntityMetrics:
    def test_perfect_match_yields_precision_recall_one(self):
        gt = ClauseGroundTruth(
            case_id="e1",
            text="A fee of 5%.",
            split=DatasetSplit.DEV,
            label_kind="positive",
            entities=(GroundTruthEntity("percentage", "5%", "5"),),
        )
        predicted = [_FakeEntity("percentage", "5%", "5", 9, 11)]
        report = evaluate_entities([(gt, predicted)])
        assert report.precision == 1.0
        assert report.recall == 1.0
        assert report.value_correctness_rate == 1.0

    def test_missed_entity_is_a_false_negative(self):
        gt = ClauseGroundTruth(
            case_id="e2",
            text="A fee of 5%.",
            split=DatasetSplit.DEV,
            label_kind="positive",
            entities=(GroundTruthEntity("percentage", "5%", "5"),),
        )
        report = evaluate_entities([(gt, [])])
        assert report.precision == 0.0  # no TP, no FP -> 0/0 defined as 0.0
        assert report.recall == 0.0

    def test_unexpected_extraction_is_a_false_positive(self):
        gt = ClauseGroundTruth(
            case_id="e3",
            text="Boilerplate clause.",
            split=DatasetSplit.DEV,
            label_kind="negative",
            entities=(),
        )
        predicted = [_FakeEntity("percentage", "5%", "5", 0, 2)]
        report = evaluate_entities([(gt, predicted)])
        assert report.precision == 0.0
        assert report.false_positive_rate == 1.0

    def test_unsupported_pattern_correctly_extracts_nothing_is_not_penalized(self):
        gt = ClauseGroundTruth(
            case_id="e4",
            text="5 percent applies.",
            split=DatasetSplit.DEV,
            label_kind="negative",
            entities=(GroundTruthEntity("percentage", "5 percent", None, expected_to_be_extracted=False),),
        )
        report = evaluate_entities([(gt, [])])
        assert report.precision == 0.0  # no TP and no FP -> defined as 0.0, not penalized
        assert report.false_positive_rate == 0.0

    def test_wrong_normalized_value_fails_value_correctness_but_not_precision(self):
        gt = ClauseGroundTruth(
            case_id="e5",
            text="A fee of 5%.",
            split=DatasetSplit.DEV,
            label_kind="positive",
            entities=(GroundTruthEntity("percentage", "5%", "5"),),
        )
        predicted = [_FakeEntity("percentage", "5%", "WRONG", 9, 11)]
        report = evaluate_entities([(gt, predicted)])
        assert report.precision == 1.0  # matched on (type, raw_text)
        assert report.value_correctness_rate == 0.0

    def test_span_inconsistency_detected(self):
        gt = ClauseGroundTruth(
            case_id="e6",
            text="A fee of 5%.",
            split=DatasetSplit.DEV,
            label_kind="positive",
            entities=(GroundTruthEntity("percentage", "5%", "5"),),
        )
        # start/end don't actually bound "5%" in gt.text.
        predicted = [_FakeEntity("percentage", "5%", "5", 0, 2)]
        report = evaluate_entities([(gt, predicted)])
        assert report.span_consistency_rate == 0.0


@dataclass(frozen=True, slots=True)
class _FakeCondition:
    trigger: str | None
    condition: str | None
    consequence: str | None
    affected_party: str | None


class TestConditionMetrics:
    def test_exact_match_on_all_fields(self):
        gt = ClauseGroundTruth(
            case_id="c1",
            text="If X, Y.",
            split=DatasetSplit.DEV,
            label_kind="positive",
            trigger="If X",
            consequence="Y",
        )
        predicted = _FakeCondition(trigger="If X", condition=None, consequence="Y", affected_party=None)
        report = evaluate_conditions([(gt, predicted)])
        assert report.chain_completeness_accuracy == 1.0
        trigger_metrics = next(f for f in report.by_field if f.field == "trigger")
        assert trigger_metrics.accuracy == 1.0

    def test_none_gold_matched_by_none_prediction_counts_correct(self):
        gt = ClauseGroundTruth(
            case_id="c2", text="Boilerplate.", split=DatasetSplit.DEV, label_kind="negative"
        )
        predicted = _FakeCondition(trigger=None, condition=None, consequence=None, affected_party=None)
        report = evaluate_conditions([(gt, predicted)])
        for f in report.by_field:
            assert f.accuracy == 1.0
            assert f.support == 0  # gold is None, doesn't count toward "presence" support

    def test_wrong_field_text_is_not_correct_even_if_both_present(self):
        gt = ClauseGroundTruth(
            case_id="c3", text="If X, Y.", split=DatasetSplit.DEV, label_kind="positive", trigger="If X"
        )
        predicted = _FakeCondition(trigger="If Z", condition=None, consequence=None, affected_party=None)
        report = evaluate_conditions([(gt, predicted)])
        trigger_metrics = next(f for f in report.by_field if f.field == "trigger")
        assert trigger_metrics.accuracy == 0.0
        assert trigger_metrics.presence_recall == 1.0  # something was found, just not the right text

    def test_partial_vs_full_chain_completeness_mismatch_detected(self):
        gt = ClauseGroundTruth(
            case_id="c4",
            text="If X, Y.",
            split=DatasetSplit.DEV,
            label_kind="positive",
            trigger="If X",
            consequence="Y",  # gold = full
        )
        predicted = _FakeCondition(
            trigger="If X", condition=None, consequence=None, affected_party=None
        )  # partial
        report = evaluate_conditions([(gt, predicted)])
        assert report.chain_completeness_accuracy == 0.0


@dataclass(frozen=True, slots=True)
class _FakeEvidence:
    text: str
    start_char: int
    end_char: int


class TestEvidenceMetrics:
    def test_matching_verified_span_is_true_positive(self):
        gt = ClauseGroundTruth(
            case_id="ev1",
            text="A fee of 5% applies.",
            split=DatasetSplit.DEV,
            label_kind="positive",
            evidence_spans=(GroundTruthEvidenceSpan("5%", "entity"),),
        )
        verified = [_FakeEvidence("5%", 9, 11)]
        report = evaluate_evidence_clauses([(gt, verified)])
        assert report.precision == 1.0
        assert report.recall == 1.0
        assert report.citation_correctness_rate == 1.0

    def test_extra_unexpected_span_is_false_positive(self):
        gt = ClauseGroundTruth(
            case_id="ev2", text="Boilerplate.", split=DatasetSplit.DEV, label_kind="negative"
        )
        verified = [_FakeEvidence("Boilerplate", 0, 11)]
        report = evaluate_evidence_clauses([(gt, verified)])
        assert report.precision == 0.0

    def test_missing_gold_span_is_false_negative(self):
        gt = ClauseGroundTruth(
            case_id="ev3",
            text="A fee of 5% applies.",
            split=DatasetSplit.DEV,
            label_kind="positive",
            evidence_spans=(GroundTruthEvidenceSpan("5%", "entity"),),
        )
        report = evaluate_evidence_clauses([(gt, [])])
        assert report.recall == 0.0

    def test_citation_correctness_false_when_offsets_dont_match_text(self):
        gt = ClauseGroundTruth(
            case_id="ev4",
            text="A fee of 5% applies.",
            split=DatasetSplit.DEV,
            label_kind="positive",
            evidence_spans=(GroundTruthEvidenceSpan("5%", "entity"),),
        )
        # Claims "5%" but offsets 0:2 actually point at "A ".
        verified = [_FakeEvidence("5%", 0, 2)]
        report = evaluate_evidence_clauses([(gt, verified)])
        assert report.citation_correctness_rate == 0.0


class TestIntegrityProbes:
    def test_all_correct_yields_zero_leaks(self):
        results = [("p1", True, True), ("p2", False, False)]
        report = evaluate_integrity_probes(results)
        assert report.fabrication_leak_count == 0
        assert report.correctly_handled == 2

    def test_fabrication_leak_detected(self):
        results = [("p1", False, True)]  # should NOT verify, but did
        report = evaluate_integrity_probes(results)
        assert report.fabrication_leak_count == 1
        assert report.incorrectly_handled_probe_ids == ("p1",)

    def test_missed_verification_is_not_a_leak(self):
        results = [("p1", True, False)]  # should verify, didn't - a different kind of error
        report = evaluate_integrity_probes(results)
        assert report.fabrication_leak_count == 0
        assert report.correctly_handled == 0


class TestCalibrationMetrics:
    def test_perfectly_calibrated_bin_has_zero_ece(self):
        # 10 samples at confidence 0.9, 9 correct -> accuracy 0.9 exactly.
        report = compute_reliability([0.9] * 10, [True] * 9 + [False], n_bins=10)
        assert report.ece == pytest.approx(0.0, abs=1e-9)

    def test_fully_miscalibrated_hand_computed(self):
        # bin[0.1] all correct (acc=1.0, |0.1-1.0|=0.9); bin[0.9] all wrong (acc=0.0, |0.9-0|=0.9)
        # ECE = 0.5*0.9 + 0.5*0.9 = 0.9
        report = compute_reliability([0.1] * 5 + [0.9] * 5, [True] * 5 + [False] * 5, n_bins=10)
        assert report.ece == pytest.approx(0.9, abs=1e-9)

    def test_empty_input_returns_zero(self):
        report = compute_reliability([], [], n_bins=10)
        assert report.ece == 0.0
        assert report.sample_count == 0

    def test_mismatched_lengths_raise(self):
        with pytest.raises(ValueError):
            compute_reliability([0.5], [], n_bins=10)

    def test_ece_by_group_splits_correctly(self):
        confidences = [0.9, 0.9, 0.1, 0.1]
        correct = [True, True, True, True]
        groups = ["HIGH", "HIGH", "LOW", "LOW"]
        results = ece_by_group(confidences, correct, groups, n_bins=10)
        high = next(r for r in results if r.key == "HIGH")
        low = next(r for r in results if r.key == "LOW")
        assert high.ece == pytest.approx(0.1, abs=1e-9)  # |0.9-1.0|
        assert low.ece == pytest.approx(0.9, abs=1e-9)  # |0.1-1.0|


class TestIsotonicCalibration:
    def test_already_monotonic_data_is_unchanged_in_trend(self):
        conf = [0.1, 0.5, 0.9]
        correct = [False, True, True]
        model = fit_isotonic_calibration(conf, correct)
        values = list(model.y_values)
        assert values == sorted(values)

    def test_violating_sequence_is_pooled_into_monotonic_output(self):
        # y decreases then increases - a classic PAV violation.
        conf = [0.1, 0.2, 0.3, 0.4]
        correct = [False, True, False, True]  # y = [0, 1, 0, 1] - violates monotonicity
        model = fit_isotonic_calibration(conf, correct)
        values = list(model.y_values)
        assert values == sorted(values)

    def test_predict_is_monotonic_non_decreasing(self):
        conf = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]
        correct = [False, True, False, True, True, False, True, True, True, True]
        model = fit_isotonic_calibration(conf, correct)
        probes = [i / 20 for i in range(21)]
        predictions = [model.predict(p) for p in probes]
        assert all(predictions[i] <= predictions[i + 1] + 1e-9 for i in range(len(predictions) - 1))

    def test_empty_input_returns_identity_like_model(self):
        model = fit_isotonic_calibration([], [])
        assert model.predict(0.5) == 0.5  # falls back to identity when nothing was fit

    def test_mismatched_lengths_raise(self):
        with pytest.raises(ValueError):
            fit_isotonic_calibration([0.5], [])


class TestAbstentionMetrics:
    def test_perfect_abstention_detection(self):
        predicted = [True, False, True, False]
        gold_expected = [True, False, True, False]
        gold_ambiguous = [True, False, True, False]
        report = evaluate_abstention(predicted, gold_expected, gold_ambiguous)
        assert report.unknown_precision == 1.0
        assert report.unknown_recall == 1.0
        assert report.false_abstention_rate == 0.0
        assert report.ambiguity_capture_rate == 1.0

    def test_false_abstention_detected(self):
        # A clause that should NOT abstain (gold_expected=False) but did.
        predicted = [True]
        gold_expected = [False]
        gold_ambiguous = [False]
        report = evaluate_abstention(predicted, gold_expected, gold_ambiguous)
        assert report.false_abstention_rate == 1.0

    def test_missed_abstention_lowers_recall(self):
        predicted = [False]  # should have abstained but didn't
        gold_expected = [True]
        gold_ambiguous = [True]
        report = evaluate_abstention(predicted, gold_expected, gold_ambiguous)
        assert report.unknown_recall == 0.0
        assert report.ambiguity_capture_rate == 0.0

    def test_empty_input_does_not_crash(self):
        report = evaluate_abstention([], [], [])
        assert report.sample_count == 0

    def test_mismatched_lengths_raise(self):
        with pytest.raises(ValueError):
            evaluate_abstention([True], [], [])

    def test_abstention_by_group(self):
        predicted = [True, True, False, False]
        groups = ["a", "a", "b", "b"]
        results = abstention_by_group(predicted, groups)
        a = next(r for r in results if r.key == "a")
        b = next(r for r in results if r.key == "b")
        assert a.abstention_rate == 1.0
        assert b.abstention_rate == 0.0
