"""Entity-extraction evaluation metrics — Phase 6 spec SS5.

Matching is by `(entity_type, raw_text)` equality within one clause — exact,
not fuzzy — since `entity_extraction_service` is a deterministic regex
extractor and every ground-truth `raw_text` is itself an exact expected
match string (see `corpus/eval/datasets/entity_ground_truth.py`).
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from corpus.eval.schema import ClauseGroundTruth  # noqa: E402


@dataclass(frozen=True, slots=True)
class PerTypeEntityMetrics:
    entity_type: str
    precision: float
    recall: float
    f1: float
    support: int


@dataclass(frozen=True, slots=True)
class EntityEvalReport:
    case_count: int
    precision: float
    recall: float
    f1: float
    by_type: tuple[PerTypeEntityMetrics, ...]
    value_correctness_rate: float
    span_consistency_rate: float
    false_positive_rate: float


def _prf(tp: int, fp: int, fn: int) -> tuple[float, float, float]:
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0.0
    return precision, recall, f1


def evaluate_entities(cases: list[tuple[ClauseGroundTruth, list]]) -> EntityEvalReport:
    """`cases`: list of `(ground_truth, predicted_entities)` pairs, where
    `predicted_entities` are `entity_extraction_service.ExtractedEntity`
    (or any object with `entity_type`, `raw_text`, `value`, `start_char`,
    `end_char`)."""
    tp_total = fp_total = fn_total = 0
    type_counts: dict[str, dict[str, int]] = {}
    value_correct = value_checked = 0
    span_consistent = span_checked = 0
    fp_cases = 0

    for gt, predicted in cases:
        expected = [e for e in gt.entities if e.expected_to_be_extracted]
        expected_keys: set[tuple[str, str]] = {(e.entity_type, e.raw_text) for e in expected}
        expected_by_key = {(e.entity_type, e.raw_text): e for e in expected}
        predicted_keys = [(p.entity_type, p.raw_text) for p in predicted]

        matched_expected: set[tuple[str, str]] = set()
        case_fp = 0
        for p, key in zip(predicted, predicted_keys, strict=True):
            entity_type = key[0]
            type_counts.setdefault(entity_type, {"tp": 0, "fp": 0, "fn": 0})
            if key in expected_keys and key not in matched_expected:
                matched_expected.add(key)
                tp_total += 1
                type_counts[entity_type]["tp"] += 1

                gold_entity = expected_by_key[key]
                if gold_entity.normalized_value is not None:
                    value_checked += 1
                    if p.value == gold_entity.normalized_value:
                        value_correct += 1

                span_checked += 1
                # `gt.text` is the exact clause text used to produce `predicted`.
                if (
                    0 <= p.start_char <= p.end_char <= len(gt.text)
                    and gt.text[p.start_char : p.end_char] == p.raw_text
                ):
                    span_consistent += 1
            else:
                fp_total += 1
                type_counts[entity_type]["fp"] += 1
                case_fp += 1

        missed = expected_keys - matched_expected
        for key in missed:
            entity_type = key[0]
            type_counts.setdefault(entity_type, {"tp": 0, "fp": 0, "fn": 0})
            fn_total += 1
            type_counts[entity_type]["fn"] += 1

        if case_fp > 0:
            fp_cases += 1

    precision, recall, f1 = _prf(tp_total, fp_total, fn_total)

    by_type_list: list[PerTypeEntityMetrics] = []
    for entity_type, counts in sorted(type_counts.items()):
        type_precision, type_recall, type_f1 = _prf(counts["tp"], counts["fp"], counts["fn"])
        by_type_list.append(
            PerTypeEntityMetrics(
                entity_type=entity_type,
                precision=type_precision,
                recall=type_recall,
                f1=type_f1,
                support=counts["tp"] + counts["fn"],
            )
        )
    by_type = tuple(by_type_list)

    return EntityEvalReport(
        case_count=len(cases),
        precision=precision,
        recall=recall,
        f1=f1,
        by_type=by_type,
        value_correctness_rate=(value_correct / value_checked) if value_checked > 0 else 0.0,
        span_consistency_rate=(span_consistent / span_checked) if span_checked > 0 else 0.0,
        false_positive_rate=(fp_cases / len(cases)) if cases else 0.0,
    )
