#!/usr/bin/env python
"""Master regression gate — Phase 6 spec SS16-17.

`python -m corpus.eval.run_all` (or `python run_all.py` from `corpus/eval/`)
runs every evaluation area, writes one versioned/timestamped JSON report
under `corpus/eval/results/` (never overwriting a previous run), and exits
non-zero if a **hard gate** fails.

**Hard gates** (exit-code-affecting) are safety/regression invariants that
hold regardless of how small or unrepresentative the current synthetic
benchmark is:
  - zero fabrication leaks in the evidence-integrity probes
  - 100% of HIGH/MEDIUM results carry verified evidence (DEV+TEST)
  - the DEV split (the set `risk_engine_v1` was tuned against) does not
    regress below its established macro F1 floor
  - the harness itself runs to completion without an unhandled exception

**Everything else is a provisional development warning, not a gate**
(Phase 6 spec SS16: "If thresholds are not yet scientifically justified:
mark them as provisional and use them only as development warnings") —
TEST-split accuracy, segmentation/retrieval numbers, and calibration ECE are
all printed and recorded, but a low number there does not fail the run,
because the current sample sizes are too small to justify a hard numeric
bar (Phase 6 spec: "Do not manufacture statistical confidence").
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_BACKEND_DIR = _REPO_ROOT / "backend"
for _path in (str(_REPO_ROOT), str(_BACKEND_DIR)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from app.core.config import Settings  # noqa: E402
from app.models.enums import RiskCategory, RiskLevel  # noqa: E402
from app.services.condition_extraction_service import extract_condition  # noqa: E402
from app.services.entity_extraction_service import extract_financial_entities  # noqa: E402
from app.services.evidence_engine import verify_span  # noqa: E402
from app.services.risk_engine import EntitySignal, PatternSignal, score_clause  # noqa: E402
from app.services.risk_engine_config import DEFAULT_RISK_ENGINE_CONFIG  # noqa: E402
from app.services.risk_engine_metrics import evaluate_risk_engine  # noqa: E402
from app.services.segmentation_metrics import compute_boundary_metrics, predicted_boundaries  # noqa: E402
from app.services.segmentation_service import segment_document  # noqa: E402
from corpus.eval.datasets.abstention_ground_truth import ABSTENTION_CASES  # noqa: E402
from corpus.eval.datasets.adversarial_risk_cases import ADVERSARIAL_CASES  # noqa: E402
from corpus.eval.datasets.condition_ground_truth import CONDITION_CASES  # noqa: E402
from corpus.eval.datasets.entity_ground_truth import ENTITY_CASES  # noqa: E402
from corpus.eval.datasets.evidence_ground_truth import (  # noqa: E402
    EVIDENCE_CLAUSE_CASES,
    EVIDENCE_INTEGRITY_PROBES,
)
from corpus.eval.datasets.risk_test_holdout import RISK_TEST_HOLDOUT  # noqa: E402
from corpus.eval.metrics.abstention_metrics import evaluate_abstention  # noqa: E402
from corpus.eval.metrics.calibration_metrics import compute_reliability  # noqa: E402
from corpus.eval.metrics.condition_metrics import evaluate_conditions  # noqa: E402
from corpus.eval.metrics.entity_metrics import evaluate_entities  # noqa: E402
from corpus.eval.metrics.evidence_metrics import (  # noqa: E402
    evaluate_evidence_clauses,
    evaluate_integrity_probes,
)
from corpus.eval.reports.error_analysis import KNOWN_FINDINGS, summarize_by_category  # noqa: E402
from corpus.eval.versioning import build_run_metadata, timestamped_output_path  # noqa: E402
from tests.fixtures.risk_engine_benchmark import BENCHMARK_CASES as DEV_RISK_CASES  # noqa: E402
from tests.fixtures.segmentation_benchmark import (  # noqa: E402
    build_benchmark as build_segmentation_benchmark,
)

# PROVISIONAL_V2 - regression floor for the DEV split only (the set
# risk_engine_v1 was tuned against, currently 1.0 and deterministic). Not a
# claim about production accuracy - see docs/PROVISIONAL_DECISIONS.md.
_DEV_MACRO_F1_FLOOR = 0.95


def _score_risk_case(text, *, matched_patterns, document_type, low_confidence_flag):
    entities = extract_financial_entities(text)
    condition = extract_condition(text)
    entity_signals = [
        EntitySignal(e.entity_type, e.value, e.raw_text, e.start_char, e.end_char) for e in entities
    ]
    return score_clause(
        text,
        matched_patterns=list(matched_patterns),
        entities=entity_signals,
        trigger=condition.trigger,
        condition_text=condition.condition,
        consequence=condition.consequence,
        document_type=document_type,
        clause_low_confidence_flag=low_confidence_flag,
        page_number=1,
    )


def _run_segmentation() -> dict:
    pooled_predicted: set[int] = set()
    pooled_gold: set[int] = set()
    offset = 0
    for case in build_segmentation_benchmark():
        result = segment_document(case.parsed)
        pred = predicted_boundaries(result.clauses)
        pooled_predicted |= {p + offset for p in pred}
        pooled_gold |= {g + offset for g in case.gold_boundaries}
        offset += len(case.parsed.blocks) + 1
    metrics = compute_boundary_metrics(pooled_predicted, pooled_gold)
    return {"precision": metrics.precision, "recall": metrics.recall, "f1": metrics.f1, "split": "dev_only"}


def _run_entity() -> dict:
    pairs = [(c, extract_financial_entities(c.text)) for c in ENTITY_CASES]
    r = evaluate_entities(pairs)
    return {"precision": r.precision, "recall": r.recall, "f1": r.f1, "case_count": r.case_count}


def _run_condition() -> dict:
    pairs = [(c, extract_condition(c.text)) for c in CONDITION_CASES]
    r = evaluate_conditions(pairs)
    return {"chain_completeness_accuracy": r.chain_completeness_accuracy, "case_count": r.case_count}


def _run_evidence() -> dict:
    pairs = []
    for gt in EVIDENCE_CLAUSE_CASES:
        result = _score_risk_case(
            gt.text, matched_patterns=(), document_type=gt.document_type, low_confidence_flag=False
        )
        pairs.append((gt, list(result.evidence.verified)))
    clause_report = evaluate_evidence_clauses(pairs)

    probe_results = [
        (
            p.probe_id,
            p.should_verify,
            p.candidate_start is not None
            and p.candidate_end is not None
            and verify_span(p.clause_text, p.candidate_text, p.candidate_start, p.candidate_end),
        )
        for p in EVIDENCE_INTEGRITY_PROBES
    ]
    integrity = evaluate_integrity_probes(probe_results)
    return {
        "precision": clause_report.precision,
        "recall": clause_report.recall,
        "citation_correctness_rate": clause_report.citation_correctness_rate,
        "integrity_fabrication_leak_count": integrity.fabrication_leak_count,
        "integrity_probe_count": integrity.probe_count,
    }


def _run_risk(cases_source, *, use_ground_truth_shape: bool) -> tuple[dict, list, list]:
    results = []
    gold: list[RiskLevel] = []
    high_medium_evidenced = 0
    high_medium_total = 0
    for case in cases_source:
        if use_ground_truth_shape:
            text, matched, doc_type, low_conf = (
                case.text,
                (),
                case.document_type,
                case.low_confidence_flag,
            )
            gold_level = case.risk_level
        else:
            text, matched, doc_type, low_conf = (
                case.text,
                case.matched_patterns,
                case.document_type,
                case.low_confidence_flag,
            )
            gold_level = RiskLevel(case.gold_risk_level)

        result = _score_risk_case(
            text, matched_patterns=matched, document_type=doc_type, low_confidence_flag=low_conf
        )
        results.append(result)
        gold.append(gold_level)
        if result.risk_level in (RiskLevel.HIGH, RiskLevel.MEDIUM):
            high_medium_total += 1
            if len(result.evidence.verified) > 0:
                high_medium_evidenced += 1

    report = evaluate_risk_engine(results, gold)
    summary = {
        "macro_f1": report.macro_f1,
        "high_risk_precision": report.high_risk_precision,
        "high_risk_recall": report.high_risk_recall,
        "abstention_rate": report.abstention_rate,
        "high_medium_with_verified_evidence_rate": report.high_medium_with_verified_evidence_rate,
        "high_medium_total": high_medium_total,
        "high_medium_evidenced": high_medium_evidenced,
    }
    return summary, results, gold


def _run_abstention() -> dict:
    predicted_unknown, gold_expected, gold_ambiguous = [], [], []
    for case in ABSTENTION_CASES:
        matched: list = []
        if case.case_id == "abstain_wrong_document_type_category":
            matched = [
                PatternSignal(
                    0.95, 0.8, RiskCategory.INSURANCE, "waiting_period", False, "taxonomy_v1", "corpus_v1"
                )
            ]
        result = _score_risk_case(
            case.text,
            matched_patterns=matched,
            document_type=case.document_type,
            low_confidence_flag=case.low_confidence_flag,
        )
        predicted_unknown.append(result.abstained)
        gold_expected.append(case.expected_abstention)
        gold_ambiguous.append(case.ambiguous)
    r = evaluate_abstention(predicted_unknown, gold_expected, gold_ambiguous)
    return {
        "unknown_precision": r.unknown_precision,
        "unknown_recall": r.unknown_recall,
        "false_abstention_rate": r.false_abstention_rate,
        "ambiguity_capture_rate": r.ambiguity_capture_rate,
    }


def _run_calibration(dev_results, dev_gold, test_results, test_gold) -> dict:
    dev_conf = [r.confidence_score for r in dev_results]
    dev_correct = [r.risk_level == g for r, g in zip(dev_results, dev_gold, strict=True)]
    test_conf = [r.confidence_score for r in test_results]
    test_correct = [r.risk_level == g for r, g in zip(test_results, test_gold, strict=True)]
    dev_report = compute_reliability(dev_conf, dev_correct, n_bins=5)
    test_report = compute_reliability(test_conf, test_correct, n_bins=5)
    return {
        "dev_ece": dev_report.ece,
        "test_ece": test_report.ece,
        "dev_n": len(dev_conf),
        "test_n": len(test_conf),
    }


def main() -> int:
    settings = Settings()
    metadata = build_run_metadata(
        taxonomy_version=settings.taxonomy_version,
        corpus_version=settings.corpus_version,
        engine_version=DEFAULT_RISK_ENGINE_CONFIG.version,
        embedding_model=settings.embedding_model_name,
    )

    print("=" * 90)
    print("REGRESSION GATE - corpus.eval.run_all")
    print("=" * 90)
    print(f"git_commit={metadata.git_commit[:12]} git_dirty={metadata.git_dirty}")
    print(
        f"taxonomy={metadata.taxonomy_version} corpus={metadata.corpus_version} "
        f"engine={metadata.engine_version} embedding={metadata.embedding_model} "
        f"benchmark={metadata.benchmark_version}"
    )
    print()

    hard_failures: list[str] = []
    warnings: list[str] = []

    report: dict = {"metadata": metadata.to_dict()}

    print("Running segmentation (DEV only)...")
    report["segmentation"] = _run_segmentation()
    print(f"  boundary F1={report['segmentation']['f1']:.2f}")

    print("Running entity extraction...")
    report["entity"] = _run_entity()
    print(f"  F1={report['entity']['f1']:.2f}")

    print("Running condition extraction...")
    report["condition"] = _run_condition()
    print(f"  chain_completeness_accuracy={report['condition']['chain_completeness_accuracy']:.2f}")

    print("Running evidence evaluation...")
    report["evidence"] = _run_evidence()
    print(
        f"  precision={report['evidence']['precision']:.2f} "
        f"fabrication_leak_count={report['evidence']['integrity_fabrication_leak_count']}"
    )
    if report["evidence"]["integrity_fabrication_leak_count"] > 0:
        hard_failures.append(
            "HARD GATE FAILED: fabricated/wrong-offset evidence verified (fabrication_leak_count > 0)"
        )

    print("Running risk classification (DEV, TEST, ADVERSARIAL)...")
    dev_summary, dev_results, dev_gold = _run_risk(DEV_RISK_CASES, use_ground_truth_shape=False)
    test_summary, test_results, test_gold = _run_risk(RISK_TEST_HOLDOUT, use_ground_truth_shape=True)
    report["risk_dev"] = dev_summary
    report["risk_test"] = test_summary
    print(f"  DEV macro_f1={dev_summary['macro_f1']:.2f}  TEST macro_f1={test_summary['macro_f1']:.2f}")

    if dev_summary["macro_f1"] < _DEV_MACRO_F1_FLOOR:
        hard_failures.append(
            f"HARD GATE FAILED: DEV macro F1 {dev_summary['macro_f1']:.3f} fell below "
            f"regression floor {_DEV_MACRO_F1_FLOOR} (risk_engine_v1 was tuned to pass DEV)"
        )
    combined_hm_total = dev_summary["high_medium_total"] + test_summary["high_medium_total"]
    combined_hm_evidenced = dev_summary["high_medium_evidenced"] + test_summary["high_medium_evidenced"]
    if combined_hm_total > 0 and combined_hm_evidenced != combined_hm_total:
        hard_failures.append(
            "HARD GATE FAILED: not every HIGH/MEDIUM result carries verified evidence "
            f"({combined_hm_evidenced}/{combined_hm_total})"
        )
    if test_summary["macro_f1"] < 0.9:
        warnings.append(
            f"TEST macro F1 is {test_summary['macro_f1']:.2f} - expected and documented "
            "(narrow rule coverage / empty corpus, see risk_test_holdout.py), not a regression signal."
        )

    print("Running abstention evaluation...")
    report["abstention"] = _run_abstention()
    print(f"  UNKNOWN precision={report['abstention']['unknown_precision']:.2f}")

    print("Running calibration...")
    report["calibration"] = _run_calibration(dev_results, dev_gold, test_results, test_gold)
    print(
        f"  DEV ECE={report['calibration']['dev_ece']:.2f}  TEST ECE={report['calibration']['test_ece']:.2f}"
    )
    warnings.append(
        f"Calibration ECE computed on only {report['calibration']['dev_n']} DEV / "
        f"{report['calibration']['test_n']} TEST samples - not statistically meaningful; diagnostic only."
    )

    print("Running adversarial cases...")
    adversarial_summary = {"pass": 0, "fail": 0, "known_gap": 0, "soft_fail": 0, "observe": 0}
    for case in ADVERSARIAL_CASES:
        result = _score_risk_case(
            case.text,
            matched_patterns=case.matched_patterns,
            document_type=case.document_type,
            low_confidence_flag=case.low_confidence_flag,
        )
        ok = True
        if case.expected_levels is not None:
            ok = ok and (result.risk_level in case.expected_levels)
        if case.forbidden_levels:
            ok = ok and (result.risk_level not in case.forbidden_levels)
        if case.expected_levels is None and not case.forbidden_levels:
            adversarial_summary["observe"] += 1
        elif ok:
            adversarial_summary["pass"] += 1
        elif case.known_gap:
            adversarial_summary["known_gap"] += 1
        elif not case.strict:
            adversarial_summary["soft_fail"] += 1
        else:
            adversarial_summary["fail"] += 1
    report["adversarial"] = adversarial_summary
    print(f"  {adversarial_summary}")
    if adversarial_summary["fail"] > 0:
        hard_failures.append(
            f"HARD GATE FAILED: {adversarial_summary['fail']} adversarial case(s) failed a strict "
            "expectation with no known_gap label (a genuine new regression)"
        )

    report["error_analysis"] = {
        "by_category": summarize_by_category(),
        "total_findings": len(KNOWN_FINDINGS),
    }

    output_path = timestamped_output_path("run_all", metadata)
    output_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")

    print()
    print("=" * 90)
    print(f"Report written to: {output_path}")
    print("=" * 90)

    if warnings:
        print("\nWARNINGS (provisional, non-gating):")
        for w in warnings:
            print(f"  - {w}")

    if hard_failures:
        print("\nHARD GATE FAILURES:")
        for f in hard_failures:
            print(f"  - {f}")
        print("\nREGRESSION GATE: FAILED")
        return 1

    print("\nREGRESSION GATE: PASSED (all hard gates satisfied)")
    print(
        "NOTE: 'passed' means no safety-critical regression was detected on this synthetic "
        "benchmark - it is not a production-accuracy claim. See corpus/eval/README.md."
    )
    print(
        "\nNot included above (slower setup - run separately): retrieval eval "
        "(run_retrieval_eval.py, needs an embedding model + Chroma), signal ablation "
        "(run_ablation.py), threshold tuning (run_threshold_tuning.py)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
