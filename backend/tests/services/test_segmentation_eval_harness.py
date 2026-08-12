"""Evaluation harness self-correctness tests — Phase 3 spec SS12
("Tests: the harness's own correctness").

`test_segmentation_metrics.py` already proves `compute_boundary_metrics`/
`compute_diagnostics` are arithmetically correct against small hand-computed
known answers. This file additionally runs the full synthetic benchmark
(tests/fixtures/segmentation_benchmark.py) end-to-end and pins its
known-good behavior as a regression guard — if a future segmentation change
silently degrades boundary detection on these clean, controlled synthetic
cases, this test catches it. It is not a claim about real-world accuracy —
see the benchmark module's docstring and corpus/eval/run_segmentation_eval.py.
"""

from __future__ import annotations

from app.services.segmentation_metrics import compute_boundary_metrics, predicted_boundaries
from app.services.segmentation_service import segment_document, validate_invariants
from tests.fixtures.segmentation_benchmark import build_benchmark


def test_benchmark_has_cases_covering_the_required_categories():
    cases = build_benchmark()
    categories = {c.category for c in cases}
    required = {
        "clean_pdf_numbered",
        "numbered_nested",
        "lettered",
        "unstructured_prose",
        "mixed_formatting",
        "docx_headings",
        "docx_table",
        "cross_reference",
        "multi_page_clause",
        "difficult_layout",
    }
    assert required <= categories


def test_every_benchmark_case_segments_without_crashing_and_preserves_invariants():
    cases = build_benchmark()
    assert len(cases) >= 8
    for case in cases:
        result = segment_document(case.parsed)
        violations = validate_invariants(case.parsed, result)
        assert violations == [], f"{case.name}: {violations}"


def test_benchmark_overall_boundary_f1_meets_the_known_good_floor():
    # This benchmark is synthetic and clean by design — a high floor here is
    # expected and is a regression guard, not a production-accuracy claim.
    cases = build_benchmark()
    pooled_predicted: set[int] = set()
    pooled_gold: set[int] = set()
    offset = 0
    for case in cases:
        result = segment_document(case.parsed)
        pred = predicted_boundaries(result.clauses)
        pooled_predicted |= {p + offset for p in pred}
        pooled_gold |= {g + offset for g in case.gold_boundaries}
        offset += len(case.parsed.blocks) + 1

    overall = compute_boundary_metrics(pooled_predicted, pooled_gold)
    assert overall.f1 >= 0.9
    assert overall.precision >= 0.9


def test_difficult_layout_case_honestly_reports_a_recall_gap():
    # A deliberately ambiguous case: trailing unstructured prose after a
    # structured section has no boundary signal of its own, so it merges
    # into the preceding clause rather than being force-split — this test
    # documents that known, intentional limitation rather than hiding it.
    cases = {c.name: c for c in build_benchmark()}
    case = cases["difficult_layout_pdf"]
    result = segment_document(case.parsed)
    pred = predicted_boundaries(result.clauses)
    metrics = compute_boundary_metrics(pred, set(case.gold_boundaries))
    assert metrics.recall < 1.0
    assert metrics.precision == 1.0  # everything predicted was a real boundary — no false positives
