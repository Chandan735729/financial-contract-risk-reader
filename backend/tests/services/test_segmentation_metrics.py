"""Segmentation metrics tests — Dataset_and_Evaluation_Spec.md SS5, Phase 3 spec SS12."""

from __future__ import annotations

from typing import Any

import pytest

from app.services.segmentation_metrics import (
    compute_boundary_metrics,
    compute_diagnostics,
    predicted_boundaries,
)
from app.services.segmentation_models import SegmentedClause


def _clause(**overrides: Any) -> SegmentedClause:
    defaults: dict[str, Any] = {
        "clause_index": 0,
        "raw_text": "1. Clause text.",
        "section_heading": None,
        "page_number": 1,
        "start_char": 0,
        "end_char": 15,
        "segmentation_confidence": 0.9,
        "low_confidence_flag": False,
        "boundary_signal": "top_numeric",
        "block_count": 1,
        "start_block_order": 0,
    }
    defaults.update(overrides)
    return SegmentedClause(**defaults)


class TestBoundaryMetrics:
    def test_perfect_match_scores_one(self):
        m = compute_boundary_metrics({0, 5, 10}, {0, 5, 10})
        assert m.precision == 1.0
        assert m.recall == 1.0
        assert m.f1 == 1.0

    def test_no_overlap_scores_zero(self):
        m = compute_boundary_metrics({0, 5}, {1, 6})
        assert m.precision == 0.0
        assert m.recall == 0.0
        assert m.f1 == 0.0

    def test_partial_overlap(self):
        m = compute_boundary_metrics({0, 5, 10}, {0, 5, 15})
        assert m.matched_count == 2
        assert m.precision == 2 / 3
        assert m.recall == 2 / 3
        assert round(m.f1, 4) == round(2 / 3, 4)

    def test_extra_predicted_boundaries_hurt_precision_not_recall(self):
        m = compute_boundary_metrics({0, 5, 10, 15}, {0, 5})
        assert m.recall == 1.0
        assert m.precision == 0.5

    def test_missing_predicted_boundaries_hurt_recall_not_precision(self):
        m = compute_boundary_metrics({0}, {0, 5, 10})
        assert m.precision == 1.0
        assert m.recall == pytest.approx(1 / 3)

    def test_both_empty_is_perfect_match(self):
        m = compute_boundary_metrics(set(), set())
        assert m.precision == 1.0
        assert m.recall == 1.0
        assert m.f1 == 1.0

    def test_empty_prediction_against_nonempty_gold_scores_zero(self):
        # Zero predictions against a non-empty gold set is reported as 0.0
        # precision, not a "vacuous" 1.0 — a summary reading "100% precision,
        # 0% recall" for zero predictions would be misleading.
        m = compute_boundary_metrics(set(), {0, 5})
        assert m.recall == 0.0
        assert m.precision == 0.0
        assert m.f1 == 0.0

    def test_predicted_boundaries_extracts_start_block_order(self):
        clauses = (_clause(start_block_order=0), _clause(start_block_order=4), _clause(start_block_order=9))
        assert predicted_boundaries(clauses) == {0, 4, 9}


class TestDiagnostics:
    def test_empty_clause_list_returns_zeroed_report(self):
        report = compute_diagnostics(())
        assert report.clause_count == 0
        assert report.average_clause_chars == 0.0

    def test_empty_clause_rate(self):
        clauses = (_clause(raw_text="real text"), _clause(raw_text="   "))
        report = compute_diagnostics(clauses)
        assert report.empty_clause_rate == 0.5

    def test_duplicate_text_rate(self):
        clauses = (_clause(raw_text="same"), _clause(raw_text="same"), _clause(raw_text="different"))
        report = compute_diagnostics(clauses)
        assert round(report.duplicate_text_rate, 4) == round(1 / 3, 4)

    def test_average_clause_chars(self):
        clauses = (_clause(raw_text="a" * 10), _clause(raw_text="b" * 20))
        report = compute_diagnostics(clauses)
        assert report.average_clause_chars == 15.0

    def test_very_large_and_very_small_rates(self):
        clauses = (
            _clause(raw_text="x" * 5000),  # very large
            _clause(raw_text="y"),  # very small
            _clause(raw_text="z" * 100),  # neither
        )
        report = compute_diagnostics(clauses, large_threshold=4000, small_threshold=20)
        assert round(report.very_large_clause_rate, 4) == round(1 / 3, 4)
        assert round(report.very_small_clause_rate, 4) == round(1 / 3, 4)

    def test_low_confidence_rate(self):
        clauses = (_clause(low_confidence_flag=True), _clause(low_confidence_flag=False))
        report = compute_diagnostics(clauses)
        assert report.low_confidence_rate == 0.5
