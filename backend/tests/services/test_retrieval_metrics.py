"""Retrieval metrics harness correctness tests — Phase 4 spec SS17/SS24."""

from __future__ import annotations

from app.services.retrieval_metrics import evaluate_retrieval, recall_at_k, reciprocal_rank


class TestRecallAtK:
    def test_gold_at_rank_1_recalled_at_all_k(self):
        ranked = ["gold", "b", "c", "d", "e"]
        assert recall_at_k(ranked, "gold", 1) is True
        assert recall_at_k(ranked, "gold", 3) is True
        assert recall_at_k(ranked, "gold", 5) is True

    def test_gold_at_rank_3_not_recalled_at_1(self):
        ranked = ["a", "b", "gold", "d", "e"]
        assert recall_at_k(ranked, "gold", 1) is False
        assert recall_at_k(ranked, "gold", 3) is True

    def test_gold_missing_entirely(self):
        ranked = ["a", "b", "c"]
        assert recall_at_k(ranked, "gold", 5) is False

    def test_empty_ranked_list(self):
        assert recall_at_k([], "gold", 5) is False


class TestReciprocalRank:
    def test_gold_at_rank_1(self):
        assert reciprocal_rank(["gold", "b"], "gold") == 1.0

    def test_gold_at_rank_2(self):
        assert reciprocal_rank(["a", "gold", "c"], "gold") == 0.5

    def test_gold_at_rank_4(self):
        assert reciprocal_rank(["a", "b", "c", "gold"], "gold") == 0.25

    def test_gold_missing(self):
        assert reciprocal_rank(["a", "b"], "gold") == 0.0


class TestEvaluateRetrieval:
    def test_empty_queries_returns_zeroed_report(self):
        report = evaluate_retrieval([])
        assert report.query_count == 0
        assert report.recall_at_1 == 0.0
        assert report.mrr == 0.0

    def test_perfect_retrieval_all_ones(self):
        results = [(["gold1", "x"], "gold1"), (["gold2", "y"], "gold2")]
        report = evaluate_retrieval(results)
        assert report.recall_at_1 == 1.0
        assert report.recall_at_3 == 1.0
        assert report.recall_at_5 == 1.0
        assert report.mrr == 1.0

    def test_mixed_ranks_computes_correct_averages(self):
        results = [
            (["gold1", "x", "y"], "gold1"),  # rank 1 -> RR 1.0, R@1 True
            (["x", "gold2", "y"], "gold2"),  # rank 2 -> RR 0.5, R@1 False, R@3 True
            (["x", "y", "z"], "gold3"),  # missing -> RR 0.0, all False
        ]
        report = evaluate_retrieval(results)
        assert report.query_count == 3
        assert round(report.recall_at_1, 4) == round(1 / 3, 4)
        assert round(report.recall_at_3, 4) == round(2 / 3, 4)
        assert round(report.mrr, 4) == round((1.0 + 0.5 + 0.0) / 3, 4)
