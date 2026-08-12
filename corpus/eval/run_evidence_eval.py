#!/usr/bin/env python
"""Evidence evaluation harness — Grounding_and_Evidence_Spec.md SS2,
Phase 6 spec SS7.

Two parts:
1. End-to-end evidence precision/recall/citation-correctness against
   `corpus/eval/datasets/evidence_ground_truth.py::EVIDENCE_CLAUSE_CASES`
   (real entity/condition/rule extraction -> Evidence Engine).
2. Integrity probes (`EVIDENCE_INTEGRITY_PROBES`): does any wrong-offset,
   cross-clause, or fabricated candidate ever verify? This is the hard
   safety metric Phase 6 spec SS7 calls for ("percentage of HIGH/MEDIUM
   results carrying verified evidence" — the necessary condition for that
   percentage to mean anything is that fabricated evidence never verifies
   at all, which is what part 2 checks directly).

Usage: (from backend/, so `app` is importable)
    python ../corpus/eval/run_evidence_eval.py
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
from app.services.entity_extraction_service import extract_financial_entities  # noqa: E402
from app.services.evidence_engine import verify_span  # noqa: E402
from app.services.risk_engine import EntitySignal, score_clause  # noqa: E402
from corpus.eval.datasets.evidence_ground_truth import (  # noqa: E402
    EVIDENCE_CLAUSE_CASES,
    EVIDENCE_INTEGRITY_PROBES,
)
from corpus.eval.metrics.evidence_metrics import (  # noqa: E402
    evaluate_evidence_clauses,
    evaluate_integrity_probes,
)


def main() -> int:
    print("Evidence evaluation")
    print("=" * 78)

    print(f"\n-- End-to-end evidence (n={len(EVIDENCE_CLAUSE_CASES)}) --")
    pairs = []
    for gt in EVIDENCE_CLAUSE_CASES:
        entities = extract_financial_entities(gt.text)
        condition = extract_condition(gt.text)
        entity_signals = [
            EntitySignal(e.entity_type, e.value, e.raw_text, e.start_char, e.end_char) for e in entities
        ]
        result = score_clause(
            gt.text,
            matched_patterns=[],
            entities=entity_signals,
            trigger=condition.trigger,
            condition_text=condition.condition,
            consequence=condition.consequence,
            document_type=gt.document_type,
            clause_low_confidence_flag=gt.low_confidence_flag,
            page_number=1,
        )
        pairs.append((gt, list(result.evidence.verified)))

    clause_report = evaluate_evidence_clauses(pairs)
    print(
        f"  precision={clause_report.precision:.2f}  recall={clause_report.recall:.2f}  f1={clause_report.f1:.2f}"
    )
    print(f"  citation_correctness_rate={clause_report.citation_correctness_rate:.2%}")

    print(f"\n-- Integrity probes (n={len(EVIDENCE_INTEGRITY_PROBES)}) --")
    probe_results = []
    for probe in EVIDENCE_INTEGRITY_PROBES:
        actual = (
            probe.candidate_start is not None
            and probe.candidate_end is not None
            and verify_span(
                probe.clause_text, probe.candidate_text, probe.candidate_start, probe.candidate_end
            )
        )
        probe_results.append((probe.probe_id, probe.should_verify, actual))
        status = "OK" if actual == probe.should_verify else "FAIL"
        print(
            f"  [{status}] {probe.probe_id:28s} category={probe.category:16s} should_verify={probe.should_verify} actual={actual}"
        )

    integrity = evaluate_integrity_probes(probe_results)
    print(f"\n  correctly_handled: {integrity.correctly_handled}/{integrity.probe_count}")
    print(f"  fabrication_leak_count (must be 0): {integrity.fabrication_leak_count}")
    if integrity.incorrectly_handled_probe_ids:
        print(f"  FAILED PROBES: {integrity.incorrectly_handled_probe_ids}")

    print()
    print(
        "NOTE: synthetic ground truth only - not a claim of production accuracy on real "
        "documents. See Dataset_and_Evaluation_Spec.md SS4 for the real-world benchmark "
        "this does not replace."
    )
    return 1 if integrity.fabrication_leak_count > 0 else 0


if __name__ == "__main__":
    raise SystemExit(main())
