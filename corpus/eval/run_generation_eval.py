#!/usr/bin/env python
"""Generation/Grounding Guard evaluation harness — Grounding_and_Evidence_Spec.md
SS7, Phase 7 spec ("grounded explanation rate, unsupported claim rate,
citation correctness, fallback rate, generation failure rate").

Every LLM call in this script is a scripted fake (`_ScriptedClient` /
`_RaisingClient`) — never a live Anthropic API call, same requirement as
`backend/tests/services/test_generation_service.py`.

Usage: (from backend/, so `app` is importable)
    python ../corpus/eval/run_generation_eval.py
"""

from __future__ import annotations

import sys
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_BACKEND_DIR = _REPO_ROOT / "backend"
for _path in (str(_REPO_ROOT), str(_BACKEND_DIR)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from app.models.enums import ConfidenceLevel, DocumentType  # noqa: E402
from app.models.schemas import ClauseAnalysis, EvidenceSpan, FinancialEntity  # noqa: E402
from app.services.generation_models import GeneratedClaim, GeneratedExplanation  # noqa: E402
from app.services.generation_service import (  # noqa: E402
    _LLMClaim,
    _LLMGenerationOutput,
    generate_explanation,
)
from app.services.grounding_guard import (  # noqa: E402
    count_material_sentences,
    detect_uncovered_material_claims,
    grounding_guard,
)
from app.services.llm_client import LLMGenerationError  # noqa: E402
from corpus.eval.datasets.generation_ground_truth import (  # noqa: E402
    GENERATION_EVAL_CASES,
    GenerationEvalCase,
    ScriptedExplanation,
)
from corpus.eval.metrics.generation_metrics import (  # noqa: E402
    GenerationCaseResult,
    evaluate_generation_cases,
)


def _clause_analysis(case: GenerationEvalCase) -> ClauseAnalysis:
    evidence_spans = []
    for text in case.evidence_span_texts:
        start = case.clause_text.index(text)
        evidence_spans.append(
            EvidenceSpan(
                text=text, start_char=start, end_char=start + len(text), page_number=1, verified=True
            )
        )
    entities = [
        FinancialEntity(type=e.entity_type, value=e.value, unit=e.unit, raw_text=e.raw_text)
        for e in case.entities
    ]
    return ClauseAnalysis(
        clause_id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        clause_index=0,
        document_type=DocumentType.LOAN,
        section_heading=None,
        raw_text=case.clause_text,
        risk_category=case.risk_category,
        risk_subcategory=None,
        taxonomy_version="taxonomy_v1",
        trigger=None,
        condition=None,
        consequence=None,
        affected_party=None,
        financial_entities=entities,
        evidence_spans=evidence_spans,
        matched_patterns=[],
        risk_level=case.risk_level,
        risk_score=0.81,
        confidence_level=ConfidenceLevel.HIGH,
        confidence_score=0.9,
        abstained=False,
        abstain_reason=None,
        explanation=None,
        explanation_grounded=None,
        model_version="unscored",
        engine_version="risk_engine_v1",
        created_at=datetime.now(UTC),
    )


def _to_llm_output(scripted: ScriptedExplanation) -> _LLMGenerationOutput:
    return _LLMGenerationOutput(
        explanation=scripted.explanation_text,
        claims=[
            _LLMClaim(text=claim.text, type=claim.claim_type, supporting_evidence_ids=[])
            for claim in scripted.claims
        ],
    )


@dataclass
class _ScriptedClient:
    outputs: list[_LLMGenerationOutput]
    call_count: int = 0

    def generate_structured(self, *, system_prompt, user_prompt, output_schema, max_output_tokens):
        output = self.outputs[self.call_count]
        self.call_count += 1
        return output


@dataclass
class _RaisingClient:
    category: str
    calls: int = 0

    def generate_structured(self, **kwargs):
        self.calls += 1
        raise LLMGenerationError(category=self.category)


def _to_generated_explanation(scripted: ScriptedExplanation) -> GeneratedExplanation:
    return GeneratedExplanation(
        text=scripted.explanation_text,
        claims=tuple(GeneratedClaim(text=c.text, claim_type=c.claim_type) for c in scripted.claims),
    )


def _run_case(case: GenerationEvalCase) -> GenerationCaseResult:
    clause = _clause_analysis(case)
    client = _ScriptedClient(outputs=[_to_llm_output(a) for a in case.attempts])
    outcome = generate_explanation(client, clause, max_retries=1, max_output_tokens=1024)

    # First-attempt diagnostics (Phase 7's original metric + Phase 7.5's
    # independent claim-coverage diagnostics).
    first_attempt_scripted = case.attempts[0]
    first_attempt_generated = _to_generated_explanation(first_attempt_scripted)
    first_attempt_guard = grounding_guard(clause, first_attempt_generated)
    first_attempt_claim_count = len(first_attempt_generated.claims)
    first_attempt_unsupported = sum(
        1 for c in first_attempt_guard.unsupported_claims if c.claim_type != "uncovered_material_statement"
    )
    first_attempt_rejected = not first_attempt_guard.passed
    uncovered = detect_uncovered_material_claims(first_attempt_generated.text, first_attempt_generated.claims)
    material_count = count_material_sentences(first_attempt_generated.text)

    # Retry-behavior diagnostics.
    retried = len(case.attempts) > 1
    retry_succeeded = retried and outcome.explanation_grounded and outcome.attempts > 1

    # Displayed-explanation safety numbers -- only populated when something
    # was actually shown (grounded=True); a fallback case shows nothing.
    displayed_claim_count = 0
    displayed_unsupported_count = 0
    reverified_unsupported = False
    if outcome.explanation_grounded:
        accepted_scripted = case.attempts[outcome.attempts - 1]
        accepted_generated = _to_generated_explanation(accepted_scripted)
        accepted_guard = grounding_guard(clause, accepted_generated)
        accepted_uncovered = detect_uncovered_material_claims(
            accepted_generated.text, accepted_generated.claims
        )
        displayed_claim_count = len(accepted_generated.claims) + len(accepted_uncovered)
        displayed_unsupported_count = len(accepted_guard.unsupported_claims)
        reverified_unsupported = not accepted_guard.passed

    return GenerationCaseResult(
        case_id=case.case_id,
        expected_grounded=case.expect_grounded,
        actual_grounded=outcome.explanation_grounded,
        attempts=outcome.attempts,
        failure_category=outcome.failure_category,
        first_attempt_claim_count=first_attempt_claim_count,
        first_attempt_unsupported_count=first_attempt_unsupported,
        first_attempt_material_sentence_count=material_count,
        first_attempt_uncovered_material_count=len(uncovered),
        first_attempt_rejected=first_attempt_rejected,
        retried=retried,
        retry_succeeded=retry_succeeded,
        displayed_claim_count=displayed_claim_count,
        displayed_unsupported_count=displayed_unsupported_count,
        accepted_attempt_reverified_unsupported=reverified_unsupported,
    )


def _run_generation_failure_probes() -> tuple[int, int]:
    """A small, separate probe set (mirrors evidence eval's integrity
    probes) that simulates the LLM call itself failing (timeout, refusal,
    API error) -- distinct from a grounding-guard failure, and the only way
    to measure `generation_failure_rate` without a live API call.
    """
    case = GENERATION_EVAL_CASES[0]
    clause = _clause_analysis(case)
    categories = ("timeout", "refusal", "overloaded")
    failures = 0
    for category in categories:
        client = _RaisingClient(category=category)
        outcome = generate_explanation(client, clause, max_retries=1, max_output_tokens=1024)
        if outcome.failure_category == f"generation_failed:{category}":
            failures += 1
    return failures, len(categories)


def main() -> int:
    print("Generation / Grounding Guard evaluation")
    print("=" * 78)
    print(f"\n-- Scripted generation cases (n={len(GENERATION_EVAL_CASES)}) --")

    results = []
    for case in GENERATION_EVAL_CASES:
        result = _run_case(case)
        results.append(result)
        status = "OK" if result.actual_grounded == result.expected_grounded else "FAIL"
        print(
            f"  [{status}] {result.case_id:45s} expected_grounded={result.expected_grounded} "
            f"actual_grounded={result.actual_grounded} attempts={result.attempts} "
            f"failure_category={result.failure_category}"
        )

    report = evaluate_generation_cases(results)

    print(f"\n  grounded_explanation_rate={report.grounded_explanation_rate:.2%}")
    print(f"  fallback_rate={report.fallback_rate:.2%}")
    print(
        f"  unsupported_claim_rate (first-attempt, declared claims only)={report.unsupported_claim_rate:.2%}"
    )
    print(f"  claim_coverage_rate={report.claim_coverage_rate:.2%}")
    print(
        "  independent_factual_claim_detection_rate=" f"{report.independent_factual_claim_detection_rate:.2%}"
    )
    print(
        "  unsupported_factual_claim_rate (displayed explanations only, SAFETY METRIC)="
        f"{report.unsupported_factual_claim_rate:.2%}"
    )
    print(f"  explanation_rejection_rate={report.explanation_rejection_rate:.2%}")
    print(f"  retry_recovery_rate={report.retry_recovery_rate:.2%}")
    print(f"  citation_correctness_rate={report.citation_correctness_rate:.2%}")
    print(f"  unsupported_claim_leak_count (must be 0): {report.unsupported_claim_leak_count}")
    if report.incorrect_case_ids:
        print(f"  INCORRECT CASES: {report.incorrect_case_ids}")

    print("\n-- Generation-failure probes (simulated LLM call errors, n=3) --")
    handled, probe_count = _run_generation_failure_probes()
    generation_failure_rate = handled / probe_count if probe_count else 0.0
    print(f"  correctly_fell_back_to_safe_state: {handled}/{probe_count}")
    print(f"  generation_failure_rate (of probes): {generation_failure_rate:.2%}")

    print()
    print(
        "NOTE: every LLM response in this harness is a hand-scripted fixture, not a live "
        "Anthropic API call -- this measures the grounding_guard/generate_explanation "
        "mechanism's correctness on known-answer cases, not live model behavior or a "
        "production accuracy claim. See Dataset_and_Evaluation_Spec.md SS4."
    )

    return 1 if report.unsupported_claim_leak_count > 0 or handled != probe_count else 0


if __name__ == "__main__":
    raise SystemExit(main())
