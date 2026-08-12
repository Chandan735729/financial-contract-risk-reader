#!/usr/bin/env python
"""Abstention (UNKNOWN) evaluation — Phase 6 spec SS10.

Runs `corpus/eval/datasets/abstention_ground_truth.py` through the Risk
Engine and reports UNKNOWN precision/recall, abstention rate, false
abstention rate, and ambiguity-capture rate — directly answering the phase
brief's own question: "are genuinely ambiguous clauses more likely to
become UNKNOWN, or is UNKNOWN simply used because the engine is
under-confident everywhere?"

Usage: (from backend/, so `app` is importable)
    python ../corpus/eval/run_abstention_eval.py
"""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_BACKEND_DIR = _REPO_ROOT / "backend"
for _path in (str(_REPO_ROOT), str(_BACKEND_DIR)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from app.models.enums import RiskCategory  # noqa: E402
from app.services.condition_extraction_service import extract_condition  # noqa: E402
from app.services.entity_extraction_service import extract_financial_entities  # noqa: E402
from app.services.risk_engine import EntitySignal, PatternSignal, score_clause  # noqa: E402
from corpus.eval.datasets.abstention_ground_truth import ABSTENTION_CASES  # noqa: E402
from corpus.eval.metrics.abstention_metrics import abstention_by_group, evaluate_abstention  # noqa: E402


def main() -> int:
    print(f"Abstention evaluation - {len(ABSTENTION_CASES)} synthetic ground-truth cases")
    print("=" * 78)

    predicted_unknown: list[bool] = []
    gold_expected: list[bool] = []
    gold_ambiguous: list[bool] = []
    label_kinds: list[str] = []

    for case in ABSTENTION_CASES:
        entities = extract_financial_entities(case.text)
        condition = extract_condition(case.text)
        entity_signals = [
            EntitySignal(e.entity_type, e.value, e.raw_text, e.start_char, e.end_char) for e in entities
        ]
        # The one case in this dataset that requires a doc-type-inapplicable
        # retrieval match to exercise the gate (mirrors run_risk_engine_eval.py's
        # adversarial case J-equivalent).
        matched = []
        if case.case_id == "abstain_wrong_document_type_category":
            matched = [
                PatternSignal(
                    similarity_score=0.95,
                    lexical_score=0.8,
                    risk_category=RiskCategory.INSURANCE,
                    risk_subcategory="waiting_period",
                    is_negative_example=False,
                    taxonomy_version="taxonomy_v1",
                    corpus_version="corpus_v1",
                )
            ]

        result = score_clause(
            case.text,
            matched_patterns=matched,
            entities=entity_signals,
            trigger=condition.trigger,
            condition_text=condition.condition,
            consequence=condition.consequence,
            document_type=case.document_type,
            clause_low_confidence_flag=case.low_confidence_flag,
            page_number=1,
        )

        matched_expectation = result.abstained == case.expected_abstention
        status = "OK" if matched_expectation else "MISMATCH"
        print(
            f"  [{status}] {case.case_id:38s} abstained={result.abstained!s:5s} "
            f"expected={case.expected_abstention!s:5s} level={result.risk_level.value}"
        )

        predicted_unknown.append(result.abstained)
        gold_expected.append(case.expected_abstention)
        gold_ambiguous.append(case.ambiguous)
        label_kinds.append(case.label_kind)

    report = evaluate_abstention(predicted_unknown, gold_expected, gold_ambiguous)
    print("\nAbstention metrics:")
    print(f"  UNKNOWN precision:        {report.unknown_precision:.2f}")
    print(f"  UNKNOWN recall:           {report.unknown_recall:.2f}")
    print(f"  Abstention rate:          {report.abstention_rate:.2%}")
    print(
        f"  False abstention rate:    {report.false_abstention_rate:.2%}  (should-not-abstain cases wrongly abstained)"
    )
    print(
        f"  Ambiguity capture rate:   {report.ambiguity_capture_rate:.2%}  (genuinely-ambiguous cases correctly abstained)"
    )

    print("\nAbstention rate by label_kind:")
    for group in abstention_by_group(predicted_unknown, label_kinds):
        print(f"  {group.key:12s} {group.abstention_rate:.2%} (n={group.sample_count})")

    print()
    if report.false_abstention_rate > 0.0:
        print("FINDING: at least one clear, unambiguous clause was incorrectly abstained on -")
        print("this indicates under-confidence, not correct selectivity.")
    else:
        print(
            "FINDING: on this small benchmark, abstention tracks genuine ambiguity "
            "(ambiguity_capture_rate) rather than blanket under-confidence "
            "(false_abstention_rate=0%)."
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
