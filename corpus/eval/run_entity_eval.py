#!/usr/bin/env python
"""Entity-extraction evaluation harness — Dataset_and_Evaluation_Spec.md
SS5, Phase 6 spec SS5.

Runs `entity_extraction_service.extract_financial_entities` against
`corpus/eval/datasets/entity_ground_truth.py` and reports precision/recall/
F1 overall and per entity type, plus value/span correctness and
false-positive rate.

IMPORTANT: synthetic, hand-authored ground truth — see the dataset module's
docstring for exactly which "difficult cases" (Phase 6 spec SS5) the
extractor supports vs. documented-does-not.

Usage: (from backend/, so `app` is importable)
    python ../corpus/eval/run_entity_eval.py
"""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_BACKEND_DIR = _REPO_ROOT / "backend"
for _path in (str(_REPO_ROOT), str(_BACKEND_DIR)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from app.services.entity_extraction_service import extract_financial_entities  # noqa: E402
from corpus.eval.datasets.entity_ground_truth import ENTITY_CASES  # noqa: E402
from corpus.eval.metrics.entity_metrics import evaluate_entities  # noqa: E402
from corpus.eval.schema import DatasetSplit  # noqa: E402


def main() -> int:
    print(f"Entity extraction evaluation - {len(ENTITY_CASES)} synthetic ground-truth cases")
    print("=" * 78)

    for split in (DatasetSplit.DEV, DatasetSplit.TEST):
        cases = [c for c in ENTITY_CASES if c.split == split]
        if not cases:
            continue
        pairs = [(c, extract_financial_entities(c.text)) for c in cases]
        report = evaluate_entities(pairs)
        print(f"\n-- {split.value.upper()} split (n={report.case_count}) --")
        print(f"  overall: P={report.precision:.2f} R={report.recall:.2f} F1={report.f1:.2f}")
        print(f"  value_correctness_rate:  {report.value_correctness_rate:.2%}")
        print(f"  span_consistency_rate:   {report.span_consistency_rate:.2%}")
        print(f"  false_positive_rate:     {report.false_positive_rate:.2%}")
        print("  by entity_type:")
        for t in report.by_type:
            print(
                f"    {t.entity_type:15s} P={t.precision:.2f} R={t.recall:.2f} F1={t.f1:.2f} (n={t.support})"
            )

    print()
    print(
        "NOTE: synthetic ground truth only - not a claim of production accuracy on real "
        "documents. See Dataset_and_Evaluation_Spec.md SS4 for the real-world benchmark "
        "this does not replace."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
