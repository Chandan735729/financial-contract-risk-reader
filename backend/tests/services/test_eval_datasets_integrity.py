"""Ground-truth dataset integrity tests — Phase 6 spec SS1-2 ("Do not mix
tuning and final evaluation examples").

Structural sanity checks only — the *content* correctness of each dataset
(hand-verified against actual pipeline output) is exercised by
`corpus/eval/run_*.py` and documented in each dataset module's docstring,
not re-asserted here.
"""

from __future__ import annotations

from app.models.enums import RiskLevel
from corpus.eval.datasets.abstention_ground_truth import ABSTENTION_CASES
from corpus.eval.datasets.adversarial_risk_cases import ADVERSARIAL_CASES
from corpus.eval.datasets.condition_ground_truth import CONDITION_CASES
from corpus.eval.datasets.entity_ground_truth import ENTITY_CASES
from corpus.eval.datasets.evidence_ground_truth import EVIDENCE_CLAUSE_CASES, EVIDENCE_INTEGRITY_PROBES
from corpus.eval.datasets.risk_test_holdout import RISK_TEST_HOLDOUT
from corpus.eval.schema import DatasetSplit
from tests.fixtures.risk_engine_benchmark import BENCHMARK_CASES as DEV_RISK_CASES


class TestNoSplitLeakage:
    """The same clause text must never appear in both DEV and TEST for the
    risk-classification benchmark - that would defeat the point of holding
    TEST out (Phase 6 spec SS1)."""

    def test_dev_and_test_risk_cases_do_not_share_text(self):
        dev_texts = {c.text for c in DEV_RISK_CASES}
        test_texts = {c.text for c in RISK_TEST_HOLDOUT}
        assert dev_texts.isdisjoint(test_texts)

    def test_adversarial_cases_are_their_own_group(self):
        for case in ADVERSARIAL_CASES:
            assert case.case_id  # every case is identifiable


class TestCaseIdUniqueness:
    def test_entity_case_ids_unique(self):
        ids = [c.case_id for c in ENTITY_CASES]
        assert len(ids) == len(set(ids))

    def test_condition_case_ids_unique(self):
        ids = [c.case_id for c in CONDITION_CASES]
        assert len(ids) == len(set(ids))

    def test_evidence_case_ids_unique(self):
        ids = [c.case_id for c in EVIDENCE_CLAUSE_CASES]
        assert len(ids) == len(set(ids))

    def test_evidence_probe_ids_unique(self):
        ids = [p.probe_id for p in EVIDENCE_INTEGRITY_PROBES]
        assert len(ids) == len(set(ids))

    def test_abstention_case_ids_unique(self):
        ids = [c.case_id for c in ABSTENTION_CASES]
        assert len(ids) == len(set(ids))

    def test_risk_test_holdout_case_ids_unique(self):
        ids = [c.case_id for c in RISK_TEST_HOLDOUT]
        assert len(ids) == len(set(ids))

    def test_adversarial_case_ids_unique(self):
        ids = [c.case_id for c in ADVERSARIAL_CASES]
        assert len(ids) == len(set(ids))


class TestSplitAssignment:
    def test_entity_cases_all_dev_or_test(self):
        assert all(c.split in (DatasetSplit.DEV, DatasetSplit.TEST) for c in ENTITY_CASES)

    def test_condition_cases_all_dev_or_test(self):
        assert all(c.split in (DatasetSplit.DEV, DatasetSplit.TEST) for c in CONDITION_CASES)

    def test_risk_test_holdout_is_all_test_split(self):
        assert all(c.split == DatasetSplit.TEST for c in RISK_TEST_HOLDOUT)

    def test_every_dataset_has_both_dev_and_test_cases(self):
        for name, cases in (("entity", ENTITY_CASES), ("condition", CONDITION_CASES)):
            splits = {c.split for c in cases}
            assert DatasetSplit.DEV in splits, f"{name} has no DEV cases"
            assert DatasetSplit.TEST in splits, f"{name} has no TEST cases"


class TestPositiveNegativeAmbiguousCoverage:
    """Phase 6 spec SS2: the benchmark must contain POSITIVE, NEGATIVE, and
    AMBIGUOUS examples."""

    def test_abstention_dataset_has_ambiguous_and_non_ambiguous_cases(self):
        ambiguous = [c for c in ABSTENTION_CASES if c.ambiguous]
        non_ambiguous = [c for c in ABSTENTION_CASES if not c.ambiguous]
        assert ambiguous
        assert non_ambiguous

    def test_entity_dataset_has_positive_and_negative_cases(self):
        label_kinds = {c.label_kind for c in ENTITY_CASES}
        assert "positive" in label_kinds
        assert "negative" in label_kinds

    def test_risk_dev_benchmark_covers_all_four_levels(self):
        levels = {RiskLevel(c.gold_risk_level) for c in DEV_RISK_CASES}
        assert levels == {RiskLevel.HIGH, RiskLevel.MEDIUM, RiskLevel.LOW, RiskLevel.UNKNOWN}


class TestAdversarialCaseSemantics:
    def test_every_case_has_a_pass_fail_or_observe_path(self):
        for case in ADVERSARIAL_CASES:
            has_assertion = case.expected_levels is not None or bool(case.forbidden_levels)
            # A case is either scorable (has an assertion) or explicitly
            # observational (Case E) - never silently neither.
            assert has_assertion or case.spec_expectation

    def test_expected_and_forbidden_never_both_unset_unless_explicitly_observational(self):
        observational_ids = {"E"}
        for case in ADVERSARIAL_CASES:
            if case.expected_levels is None and not case.forbidden_levels:
                assert (
                    case.case_id in observational_ids
                ), f"{case.case_id} has no assertion and isn't marked observational"


class TestGroundTruthSchemaInvariant:
    def test_expected_abstention_implies_unknown_across_all_datasets(self):
        for cases in (
            ABSTENTION_CASES,
            ENTITY_CASES,
            CONDITION_CASES,
            EVIDENCE_CLAUSE_CASES,
            RISK_TEST_HOLDOUT,
        ):
            for case in cases:
                if case.expected_abstention:
                    assert case.risk_level == RiskLevel.UNKNOWN
