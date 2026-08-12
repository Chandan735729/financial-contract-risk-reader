"""Evidence evaluation metrics — Phase 6 spec SS7, Grounding_and_Evidence_Spec.md SS2.

`evaluate_evidence_clauses` measures end-to-end evidence precision/recall
against `corpus/eval/datasets/evidence_ground_truth.py::EVIDENCE_CLAUSE_CASES`.
"Citation correctness" is reported as a rate over the *verified* spans only
(Grounding_and_Evidence_Spec.md SS3) — this is expected to be 100% by
construction, since `evidence_engine.verify_span` already guarantees every
verified span is an exact/normalized substring of `raw_text`; reporting it
here turns that invariant into a measured, regression-checkable number
rather than an assumption.

`evaluate_integrity_probes` measures the safety-critical property directly:
does a fabricated/mis-offset/cross-clause candidate ever verify? (Phase 6
spec SS7: "Track: percentage of HIGH/MEDIUM results carrying verified
evidence. This should be a hard safety metric.")
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
class EvidenceEvalReport:
    case_count: int
    precision: float
    recall: float
    f1: float
    citation_correctness_rate: float  # of verified spans, fraction that are genuine raw_text substrings


def _normalize(text: str) -> str:
    return " ".join(text.split()).strip()


def evaluate_evidence_clauses(cases: list[tuple[ClauseGroundTruth, list]]) -> EvidenceEvalReport:
    """`cases`: `(ground_truth, verified_evidence)` pairs, where
    `verified_evidence` is `evidence_engine.EvidenceResult.verified` (or any
    sequence of objects with `.text`, `.start_char`, `.end_char`)."""
    tp_total = fp_total = fn_total = 0
    citation_correct = citation_checked = 0

    for gt, verified in cases:
        gold_texts = {_normalize(s.text) for s in gt.evidence_spans}
        predicted_texts = [_normalize(v.text) for v in verified]

        matched_gold: set[str] = set()
        for text in predicted_texts:
            if text in gold_texts and text not in matched_gold:
                matched_gold.add(text)
                tp_total += 1
            else:
                fp_total += 1
        fn_total += len(gold_texts - matched_gold)

        for v in verified:
            citation_checked += 1
            actual = (
                gt.text[v.start_char : v.end_char] if 0 <= v.start_char <= v.end_char <= len(gt.text) else ""
            )
            if _normalize(actual) == _normalize(v.text):
                citation_correct += 1

    precision = tp_total / (tp_total + fp_total) if (tp_total + fp_total) > 0 else 0.0
    recall = tp_total / (tp_total + fn_total) if (tp_total + fn_total) > 0 else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0.0

    return EvidenceEvalReport(
        case_count=len(cases),
        precision=precision,
        recall=recall,
        f1=f1,
        citation_correctness_rate=(citation_correct / citation_checked) if citation_checked > 0 else 0.0,
    )


@dataclass(frozen=True, slots=True)
class IntegrityProbeReport:
    probe_count: int
    correctly_handled: int
    fabrication_leak_count: int  # count of probes where a should-NOT-verify candidate DID verify — must be 0
    incorrectly_handled_probe_ids: tuple[str, ...]


def evaluate_integrity_probes(results: list[tuple[str, bool, bool]]) -> IntegrityProbeReport:
    """`results`: `(probe_id, should_verify, actually_verified)` triples."""
    correct = 0
    leaks = 0
    bad_ids: list[str] = []
    for probe_id, should_verify, actually_verified in results:
        if should_verify == actually_verified:
            correct += 1
        else:
            bad_ids.append(probe_id)
            if actually_verified and not should_verify:
                leaks += 1

    return IntegrityProbeReport(
        probe_count=len(results),
        correctly_handled=correct,
        fabrication_leak_count=leaks,
        incorrectly_handled_probe_ids=tuple(bad_ids),
    )
