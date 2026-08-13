"""Generation/Grounding Guard evaluation metrics — Phase 7.5 SS10.

Phase 7's `unsupported_claim_rate` measured only the model's
self-*declared* `claims[]` on the *first* attempt — diagnostically useful,
but easy to misread as a safety number when it isn't one (see
`docs/EXPLANATION_GROUNDING_NOTES.md` SS3 for the full root-cause
writeup: on Phase 7's own eval dataset, 55.6% simply meant "the guard
correctly rejected 100% of the deliberately-scripted adversarial
first-attempt probes," not "56% of shown explanations are unsupported").

This module keeps that number (documented precisely) and adds the metrics
Phase 7.5 SS10 asks for, each defined exactly once here:

| Metric | What it measures |
|---|---|
| `unsupported_claim_rate` | (Phase 7, unchanged formula) fraction of first-attempt, model-*declared* `claims[]` entries that fail `supported_by_evidence`. A generation-quality diagnostic, not a safety metric — expect a non-trivial number on any dataset that deliberately includes failure probes. |
| `claim_coverage_rate` | Fraction of independently-detected material sentences (`grounding_guard.detect_uncovered_material_claims`) in the *first* attempt's `explanation` that a declared claim already covers. 1.0 means the model's `claims[]` was a complete decomposition of its own prose. |
| `independent_factual_claim_detection_rate` | Fraction of cases where the independent detector found at least one uncovered material sentence in the first attempt. Diagnostic: how often does the coverage gap actually bite. |
| `unsupported_factual_claim_rate` | Fraction of all factual claims — declared **and** independently-detected — that fail `supported_by_evidence`, counted only across explanations that were actually **displayed** (the final accepted attempt; nothing is counted for a case that ends in fallback, since nothing was shown). **This is the safety-relevant number** the Phase 7 headline figure was mistaken for. |
| `explanation_rejection_rate` | Fraction of cases where the **first** attempt failed the guard, regardless of whether a retry recovered it. |
| `retry_recovery_rate` | Of cases whose first attempt was rejected *and* which had a retry attempt available, the fraction that passed on that retry. |
| `fallback_rate` | (Phase 7, unchanged) fraction of cases whose *final* state is the safe fallback (`explanation=None`). |
| `grounded_explanation_rate` | (Phase 7, unchanged) fraction of cases whose final, displayed explanation is grounded. |
| `unsupported_claim_leak_count` | (Phase 7, unchanged, hard gate) count of cases where a *displayed* explanation, independently re-verified, is still found to carry an unsupported claim. Must be 0. |
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class GenerationCaseResult:
    case_id: str
    expected_grounded: bool
    actual_grounded: bool
    attempts: int
    failure_category: str | None

    # First-attempt diagnostics (Phase 7's original unsupported_claim_rate).
    first_attempt_claim_count: int
    first_attempt_unsupported_count: int

    # Independent claim-coverage diagnostics (Phase 7.5 SS2/SS10), first
    # attempt only.
    first_attempt_material_sentence_count: int
    first_attempt_uncovered_material_count: int

    # Retry-behavior diagnostics (Phase 7.5 SS10).
    first_attempt_rejected: bool
    retried: bool
    retry_succeeded: bool

    # Displayed-explanation safety numbers (Phase 7.5 SS10) — zero for a
    # case that ends in fallback, since nothing was shown to a user.
    displayed_claim_count: int
    displayed_unsupported_count: int

    # Independent re-verification of the specific attempt that was accepted
    # as grounded (only meaningful when `actual_grounded` is True) -- see
    # module docstring / `unsupported_claim_leak_count`.
    accepted_attempt_reverified_unsupported: bool


@dataclass(frozen=True, slots=True)
class GenerationEvalReport:
    case_count: int
    grounded_explanation_rate: float
    fallback_rate: float
    unsupported_claim_rate: float
    claim_coverage_rate: float
    independent_factual_claim_detection_rate: float
    unsupported_factual_claim_rate: float
    explanation_rejection_rate: float
    retry_recovery_rate: float
    citation_correctness_rate: float  # fraction of cases whose final grounded/fallback outcome matches gold
    generation_failure_rate: float  # fraction of cases where the (simulated) LLM call itself errored
    unsupported_claim_leak_count: int  # MUST be 0 -- hard safety metric, see module docstring
    incorrect_case_ids: tuple[str, ...]


def evaluate_generation_cases(results: Sequence[GenerationCaseResult]) -> GenerationEvalReport:
    n = len(results)
    grounded = sum(1 for r in results if r.actual_grounded)
    correct = sum(1 for r in results if r.actual_grounded == r.expected_grounded)

    total_claims = sum(r.first_attempt_claim_count for r in results)
    total_unsupported = sum(r.first_attempt_unsupported_count for r in results)

    total_material = sum(r.first_attempt_material_sentence_count for r in results)
    total_uncovered = sum(r.first_attempt_uncovered_material_count for r in results)
    cases_with_uncovered = sum(1 for r in results if r.first_attempt_uncovered_material_count > 0)

    rejected_first = [r for r in results if r.first_attempt_rejected]
    retried_after_rejection = [r for r in rejected_first if r.retried]
    retry_succeeded_count = sum(1 for r in retried_after_rejection if r.retry_succeeded)

    total_displayed_claims = sum(r.displayed_claim_count for r in results)
    total_displayed_unsupported = sum(r.displayed_unsupported_count for r in results)

    generation_failures = sum(
        1
        for r in results
        if r.failure_category is not None and r.failure_category.startswith("generation_failed:")
    )
    leaks = [r.case_id for r in results if r.actual_grounded and r.accepted_attempt_reverified_unsupported]
    incorrect = tuple(r.case_id for r in results if r.actual_grounded != r.expected_grounded)

    return GenerationEvalReport(
        case_count=n,
        grounded_explanation_rate=(grounded / n) if n else 0.0,
        fallback_rate=((n - grounded) / n) if n else 0.0,
        unsupported_claim_rate=(total_unsupported / total_claims) if total_claims else 0.0,
        claim_coverage_rate=((total_material - total_uncovered) / total_material) if total_material else 1.0,
        independent_factual_claim_detection_rate=(cases_with_uncovered / n) if n else 0.0,
        unsupported_factual_claim_rate=(
            (total_displayed_unsupported / total_displayed_claims) if total_displayed_claims else 0.0
        ),
        explanation_rejection_rate=(len(rejected_first) / n) if n else 0.0,
        retry_recovery_rate=(
            (retry_succeeded_count / len(retried_after_rejection)) if retried_after_rejection else 0.0
        ),
        citation_correctness_rate=(correct / n) if n else 0.0,
        generation_failure_rate=(generation_failures / n) if n else 0.0,
        unsupported_claim_leak_count=len(leaks),
        incorrect_case_ids=incorrect,
    )
