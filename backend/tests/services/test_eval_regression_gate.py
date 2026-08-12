"""Regression-gate integration tests — Phase 6 spec SS16, SS19 ("regression
detection").

Runs the actual `corpus.eval.run_all.main()` entry point (not a subprocess)
to prove the master gate executes end-to-end and correctly distinguishes
hard failures from provisional warnings.
"""

from __future__ import annotations

import glob
import os

from corpus.eval import run_all
from corpus.eval.versioning import results_dir


def _cleanup_generated_reports(before: set[str]) -> None:
    after = set(glob.glob(str(results_dir() / "*.json")))
    for path in after - before:
        os.remove(path)


def test_run_all_completes_and_passes_on_a_clean_checkout():
    before = set(glob.glob(str(results_dir() / "*.json")))
    try:
        exit_code = run_all.main()
        assert exit_code == 0
    finally:
        _cleanup_generated_reports(before)


def test_run_all_writes_a_new_versioned_report_each_run():
    before = set(glob.glob(str(results_dir() / "*.json")))
    try:
        run_all.main()
        after_one = set(glob.glob(str(results_dir() / "*.json")))
        new_files_one = after_one - before
        assert len(new_files_one) == 1

        run_all.main()
        after_two = set(glob.glob(str(results_dir() / "*.json")))
        new_files_two = after_two - before
        # The second run adds a distinct file - it never overwrote the first.
        assert len(new_files_two) == 2
    finally:
        _cleanup_generated_reports(before)


def test_hard_gate_catches_a_fabrication_leak(monkeypatch):
    """Simulates a hard-gate failure by monkeypatching the evidence step to
    report a fabrication leak, and asserts the gate actually fails (exit
    code 1) rather than silently passing - this is the regression-detection
    behavior itself under test, not just the happy path."""
    before = set(glob.glob(str(results_dir() / "*.json")))

    def _broken_evidence() -> dict:
        return {
            "precision": 1.0,
            "recall": 1.0,
            "citation_correctness_rate": 1.0,
            "integrity_fabrication_leak_count": 1,  # simulated failure
            "integrity_probe_count": 6,
        }

    monkeypatch.setattr(run_all, "_run_evidence", _broken_evidence)
    try:
        exit_code = run_all.main()
        assert exit_code == 1
    finally:
        _cleanup_generated_reports(before)


def test_hard_gate_catches_dev_macro_f1_regression(monkeypatch):
    """Simulates a DEV-split regression (risk_engine_v1 should always score
    1.0 macro F1 on the set it was tuned against) and asserts the gate
    fails."""
    before = set(glob.glob(str(results_dir() / "*.json")))
    original_run_risk = run_all._run_risk

    def _regressed_run_risk(cases_source, *, use_ground_truth_shape: bool):
        summary, results, gold = original_run_risk(
            cases_source, use_ground_truth_shape=use_ground_truth_shape
        )
        if not use_ground_truth_shape:  # this is the DEV call
            summary = dict(summary)
            summary["macro_f1"] = 0.5  # simulated regression
        return summary, results, gold

    monkeypatch.setattr(run_all, "_run_risk", _regressed_run_risk)
    try:
        exit_code = run_all.main()
        assert exit_code == 1
    finally:
        _cleanup_generated_reports(before)
