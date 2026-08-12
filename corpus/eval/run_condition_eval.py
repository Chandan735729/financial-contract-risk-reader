#!/usr/bin/env python
"""Condition-extraction evaluation harness — Dataset_and_Evaluation_Spec.md
SS5, Phase 6 spec SS6.

Runs `condition_extraction_service.extract_condition` against
`corpus/eval/datasets/condition_ground_truth.py` and reports per-field
exact-match accuracy plus trigger/condition/consequence chain-completeness
accuracy.

IMPORTANT: three of the seven adversarial connectives Phase 6 spec SS6
requires testing ("provided that," "subject to," "notwithstanding") are
**not recognized by the current extractor** — see the dataset module's
docstring. This is reported here as a real, load-bearing finding, not
smoothed over.

Usage: (from backend/, so `app` is importable)
    python ../corpus/eval/run_condition_eval.py
"""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_BACKEND_DIR = _REPO_ROOT / "backend"
for _path in (str(_REPO_ROOT), str(_BACKEND_DIR)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from app.services.condition_extraction_service import extract_condition  # noqa: E402
from corpus.eval.datasets.condition_ground_truth import CONDITION_CASES  # noqa: E402
from corpus.eval.metrics.condition_metrics import evaluate_conditions  # noqa: E402
from corpus.eval.schema import DatasetSplit  # noqa: E402


def main() -> int:
    print(f"Condition extraction evaluation - {len(CONDITION_CASES)} synthetic ground-truth cases")
    print("=" * 78)

    for split in (DatasetSplit.DEV, DatasetSplit.TEST):
        cases = [c for c in CONDITION_CASES if c.split == split]
        if not cases:
            continue
        pairs = [(c, extract_condition(c.text)) for c in cases]
        report = evaluate_conditions(pairs)
        print(f"\n-- {split.value.upper()} split (n={report.case_count}) --")
        print(f"  chain_completeness_accuracy: {report.chain_completeness_accuracy:.2%}")
        for f in report.by_field:
            print(
                f"    {f.field:16s} exact_accuracy={f.accuracy:.2%} "
                f"presence_recall={f.presence_recall:.2%} (support={f.support})"
            )

    print(
        "\nKnown unsupported connectives (see module docstring): 'provided that', 'subject to', 'notwithstanding'."
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
