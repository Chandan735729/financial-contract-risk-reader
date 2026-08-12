"""Segmentation evaluation metrics — Dataset_and_Evaluation_Spec.md SS5
("Segmentation: Boundary precision, boundary recall, F1"), Phase 3 spec SS12.

Boundary positions are `DocumentTextBlock.order` values (Phase 2's own
reading-order counter) — the block that begins each predicted/gold clause.
This scores "did we start a new clause at the same point a human annotator
would," independent of exact `raw_text` string content, join-separator
choices, or normalization differences.

This module deliberately does not claim to measure production accuracy —
see `corpus/eval/run_segmentation_eval.py` and
docs/PROVISIONAL_DECISIONS.md "Phase 3: segmentation evaluation is
synthetic-only" for what these numbers do and do not represent.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.services.segmentation_models import SegmentedClause


@dataclass(frozen=True, slots=True)
class BoundaryMetrics:
    precision: float
    recall: float
    f1: float
    predicted_count: int
    gold_count: int
    matched_count: int


def predicted_boundaries(clauses: tuple[SegmentedClause, ...]) -> set[int]:
    return {c.start_block_order for c in clauses}


def compute_boundary_metrics(predicted: set[int], gold: set[int]) -> BoundaryMetrics:
    """Standard set-based precision/recall/F1 over boundary positions.

    Edge cases: an empty gold set with an empty prediction is a perfect
    match (precision=recall=1.0); an empty prediction against a non-empty
    gold set (or vice versa) scores 0 on the side with no positions to
    match, rather than raising a ZeroDivisionError.
    """
    matched = predicted & gold

    precision = len(matched) / len(predicted) if predicted else (1.0 if not gold else 0.0)
    recall = len(matched) / len(gold) if gold else (1.0 if not predicted else 0.0)
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0.0

    return BoundaryMetrics(
        precision=precision,
        recall=recall,
        f1=f1,
        predicted_count=len(predicted),
        gold_count=len(gold),
        matched_count=len(matched),
    )


@dataclass(frozen=True, slots=True)
class SegmentationDiagnosticsReport:
    clause_count: int
    empty_clause_rate: float
    duplicate_text_rate: float
    average_clause_chars: float
    very_large_clause_rate: float
    very_small_clause_rate: float
    low_confidence_rate: float


def compute_diagnostics(
    clauses: tuple[SegmentedClause, ...],
    *,
    large_threshold: int = 4000,
    small_threshold: int = 20,
) -> SegmentationDiagnosticsReport:
    if not clauses:
        return SegmentationDiagnosticsReport(
            clause_count=0,
            empty_clause_rate=0.0,
            duplicate_text_rate=0.0,
            average_clause_chars=0.0,
            very_large_clause_rate=0.0,
            very_small_clause_rate=0.0,
            low_confidence_rate=0.0,
        )

    n = len(clauses)
    texts = [c.raw_text for c in clauses]
    empty = sum(1 for t in texts if not t.strip())
    # Count of clauses whose text is *not* unique among all clauses' texts —
    # i.e. every occurrence past the first of a repeated string.
    duplicate = n - len(set(texts))
    avg_chars = sum(len(t) for t in texts) / n
    very_large = sum(1 for t in texts if len(t) >= large_threshold)
    very_small = sum(1 for t in texts if len(t) < small_threshold)
    low_confidence = sum(1 for c in clauses if c.low_confidence_flag)

    return SegmentationDiagnosticsReport(
        clause_count=n,
        empty_clause_rate=empty / n,
        duplicate_text_rate=duplicate / n,
        average_clause_chars=avg_chars,
        very_large_clause_rate=very_large / n,
        very_small_clause_rate=very_small / n,
        low_confidence_rate=low_confidence / n,
    )
