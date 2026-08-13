"""Generation/Grounding Guard evaluation metrics — Phase 7 spec ("grounded
explanation rate, unsupported claim rate, citation correctness, fallback
rate, generation failure rate").

`unsupported_claim_leak_count` is the hard safety metric, mirroring
`evidence_metrics.IntegrityProbeReport.fabrication_leak_count`: it
independently re-runs `grounding_guard` against whichever attempt
`generate_explanation` actually accepted as grounded, so "an explanation
with an unsupported claim is never marked grounded" is a *measured,
regression-checkable* number, not only a code-review assumption.
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
    first_attempt_claim_count: int
    first_attempt_unsupported_count: int
    # Independent re-verification of the specific attempt that was accepted
    # as grounded (only meaningful when `actual_grounded` is True) -- see
    # module docstring.
    accepted_attempt_reverified_unsupported: bool


@dataclass(frozen=True, slots=True)
class GenerationEvalReport:
    case_count: int
    grounded_explanation_rate: float
    fallback_rate: float
    unsupported_claim_rate: float
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
        citation_correctness_rate=(correct / n) if n else 0.0,
        generation_failure_rate=(generation_failures / n) if n else 0.0,
        unsupported_claim_leak_count=len(leaks),
        incorrect_case_ids=incorrect,
    )
