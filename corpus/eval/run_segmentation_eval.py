#!/usr/bin/env python
"""Segmentation evaluation harness — Dataset_and_Evaluation_Spec.md SS5,
Phase 3 spec SS12, Implementation_Roadmap.md Phase 5 ("should be
scaffolded early ... ready the moment [parsing] produces real output").

Runs `segment_document()` against the synthetic benchmark
(backend/tests/fixtures/segmentation_benchmark.py) and reports boundary
precision/recall/F1 plus segmentation-quality diagnostics.

IMPORTANT — READ BEFORE CITING THESE NUMBERS:
This benchmark is synthetic and hand-authored for development/regression
purposes. It is NOT the real-world benchmark Dataset_and_Evaluation_Spec.md
SS4 requires (independently annotated real documents, messy/scanned/varied
sources, inter-annotator agreement). These numbers demonstrate the
evaluation harness works and give a directional sanity check on the rule
engine against clean, known-structure synthetic documents — they say
nothing about production accuracy on real, messy financial contracts. Do
not report these numbers as production accuracy.

Usage: (from backend/, so `app` is importable)
    python ../corpus/eval/run_segmentation_eval.py
"""

from __future__ import annotations

import sys
from pathlib import Path

_BACKEND_DIR = Path(__file__).resolve().parents[2] / "backend"
sys.path.insert(0, str(_BACKEND_DIR))

from app.services.segmentation_metrics import (  # noqa: E402
    compute_boundary_metrics,
    compute_diagnostics,
    predicted_boundaries,
)
from app.services.segmentation_models import SegmentedClause  # noqa: E402
from app.services.segmentation_service import segment_document  # noqa: E402
from tests.fixtures.segmentation_benchmark import build_benchmark  # noqa: E402


def main() -> int:
    cases = build_benchmark()
    if not cases:
        print("No benchmark cases found — nothing to evaluate.")
        return 1

    print(f"Segmentation evaluation — {len(cases)} synthetic benchmark cases")
    print("=" * 78)
    print(f"{'case':35s} {'category':20s} {'P':>5s} {'R':>5s} {'F1':>5s}")
    print("-" * 78)

    pooled_predicted: set[int] = set()
    pooled_gold: set[int] = set()
    offset = 0
    all_clauses: list[SegmentedClause] = []

    for case in cases:
        result = segment_document(case.parsed)
        all_clauses.extend(result.clauses)

        pred = predicted_boundaries(result.clauses)
        metrics = compute_boundary_metrics(pred, set(case.gold_boundaries))
        print(
            f"{case.name:35s} {case.category:20s} "
            f"{metrics.precision:5.2f} {metrics.recall:5.2f} {metrics.f1:5.2f}"
        )

        pooled_predicted |= {p + offset for p in pred}
        pooled_gold |= {g + offset for g in case.gold_boundaries}
        offset += len(case.parsed.blocks) + 1  # +1 guard gap between documents

    print("-" * 78)
    overall = compute_boundary_metrics(pooled_predicted, pooled_gold)
    print(
        f"{'OVERALL (micro-averaged)':56s} {overall.precision:5.2f} {overall.recall:5.2f} {overall.f1:5.2f}"
    )
    print()

    diagnostics = compute_diagnostics(tuple(all_clauses))
    print("Diagnostics across all benchmark clauses:")
    print(f"  clause_count            {diagnostics.clause_count}")
    print(f"  empty_clause_rate       {diagnostics.empty_clause_rate:.2%}")
    print(f"  duplicate_text_rate     {diagnostics.duplicate_text_rate:.2%}")
    print(f"  average_clause_chars    {diagnostics.average_clause_chars:.1f}")
    print(f"  very_large_clause_rate  {diagnostics.very_large_clause_rate:.2%}")
    print(f"  very_small_clause_rate  {diagnostics.very_small_clause_rate:.2%}")
    print(f"  low_confidence_rate     {diagnostics.low_confidence_rate:.2%}")
    print()
    print(
        "NOTE: synthetic benchmark only — not production accuracy. "
        "See Dataset_and_Evaluation_Spec.md SS4 for the real-world benchmark this does not replace."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
