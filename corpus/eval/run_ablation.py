#!/usr/bin/env python
"""Signal-ablation analysis — Phase 6 spec SS14.

Re-scores the DEV benchmark with each Risk Engine signal knocked out (its
weight forced to 0) and compares macro F1 / HIGH precision-recall against
the full engine, to verify the multi-signal architecture actually adds
value rather than one signal silently doing all the work.

Usage: (from backend/, so `app` and `tests` are importable)
    python ../corpus/eval/run_ablation.py
"""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_BACKEND_DIR = _REPO_ROOT / "backend"
for _path in (str(_REPO_ROOT), str(_BACKEND_DIR)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from corpus.eval.metrics.ablation import run_ablation  # noqa: E402
from tests.fixtures.risk_engine_benchmark import BENCHMARK_CASES  # noqa: E402


def main() -> int:
    print(f"Signal ablation - {len(BENCHMARK_CASES)} DEV cases, risk_engine_v1 weights zeroed per variant")
    print("=" * 80)
    print(f"{'variant':42s} {'macroF1':>8s} {'HIGH-P':>8s} {'HIGH-R':>8s} {'abstention':>11s}")
    print("-" * 80)

    results = run_ablation(list(BENCHMARK_CASES))
    full = next(r for r in results if r.variant_name == "full_engine")

    for r in results:
        marker = " <-- full engine" if r.variant_name == "full_engine" else ""
        print(
            f"{r.variant_name:42s} {r.macro_f1:8.3f} {r.high_precision:8.3f} "
            f"{r.high_recall:8.3f} {r.abstention_rate:11.2%}{marker}"
        )

    print()
    weaker_variants = [r for r in results if r.variant_name != "full_engine" and r.macro_f1 < full.macro_f1]
    print(
        f"FINDING: {len(weaker_variants)}/{len(results) - 1} ablated variants score strictly below "
        f"the full engine's macro F1 ({full.macro_f1:.2f}) on this DEV benchmark."
    )
    if len(weaker_variants) == len(results) - 1:
        print(
            "Every single-signal or partial-signal variant underperforms the full engine - "
            "no one signal is doing all the work; the weighted multi-signal combination "
            "(specifically rule_boost + the entity-corroboration bonus) is load-bearing for "
            "reaching HIGH/MEDIUM at all on this benchmark. See run_ablation.py's module "
            "docstring and docs/PROVISIONAL_DECISIONS.md for the mechanism: LOW classifications "
            "survive ablation via the rule-negation abstention override (independent of scoring "
            "weights), but HIGH/MEDIUM require the full weighted score."
        )

    print()
    print(
        "NOTE: synthetic DEV benchmark only - not a claim about signal value on real, messy "
        "documents. See Dataset_and_Evaluation_Spec.md SS4."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
