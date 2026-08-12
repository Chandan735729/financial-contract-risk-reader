"""Retrieval evaluation metrics — Dataset_and_Evaluation_Spec.md SS5
("Retrieval: Recall@1, Recall@3, Recall@5 ... MRR"), Phase 4 spec SS17/SS24.

Operates on a ranked list of `corpus_pattern_id`s (best first) against a
single known-correct ("gold") pattern id per query — the standard
single-relevant-document formulation these metrics assume. Does not claim
production retrieval performance; see `corpus/eval/run_retrieval_eval.py`
and docs/PROVISIONAL_DECISIONS.md "Phase 4: retrieval evaluation is
synthetic-only".
"""

from __future__ import annotations

from dataclasses import dataclass


def recall_at_k(ranked_ids: list[str], gold_id: str, k: int) -> bool:
    return gold_id in ranked_ids[:k]


def reciprocal_rank(ranked_ids: list[str], gold_id: str) -> float:
    for index, candidate_id in enumerate(ranked_ids, start=1):
        if candidate_id == gold_id:
            return 1.0 / index
    return 0.0


@dataclass(frozen=True, slots=True)
class RetrievalEvalReport:
    query_count: int
    recall_at_1: float
    recall_at_3: float
    recall_at_5: float
    mrr: float


def evaluate_retrieval(ranked_results: list[tuple[list[str], str]]) -> RetrievalEvalReport:
    """`ranked_results`: list of (ranked_pattern_ids, gold_pattern_id) pairs,
    one per query. Returns aggregate Recall@1/3/5 and MRR across all queries."""
    if not ranked_results:
        return RetrievalEvalReport(query_count=0, recall_at_1=0.0, recall_at_3=0.0, recall_at_5=0.0, mrr=0.0)

    n = len(ranked_results)
    r1 = sum(recall_at_k(ranked, gold, 1) for ranked, gold in ranked_results) / n
    r3 = sum(recall_at_k(ranked, gold, 3) for ranked, gold in ranked_results) / n
    r5 = sum(recall_at_k(ranked, gold, 5) for ranked, gold in ranked_results) / n
    mrr_value = sum(reciprocal_rank(ranked, gold) for ranked, gold in ranked_results) / n

    return RetrievalEvalReport(query_count=n, recall_at_1=r1, recall_at_3=r3, recall_at_5=r5, mrr=mrr_value)
