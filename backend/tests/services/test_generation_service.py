"""Generation Service orchestration tests — Grounding_and_Evidence_Spec.md
SS5 (retry-once-then-fallback). Every `GenerationLLMClient` here is a fake
in-memory implementation of the `Protocol` -- no live Anthropic API call is
ever made in this suite (Phase 7 spec requirement).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

from app.models.enums import ConfidenceLevel, DocumentType, RiskCategory, RiskLevel
from app.models.schemas import ClauseAnalysis, EvidenceSpan, FinancialEntity
from app.services.generation_config import MODEL_VERSION
from app.services.generation_service import _LLMClaim, _LLMGenerationOutput, generate_explanation
from app.services.llm_client import LLMGenerationError

_RAW_TEXT = (
    "The Borrower shall pay a prepayment penalty of 2% of the outstanding "
    "principal if the loan is repaid in full within 24 months of the "
    "disbursement date."
)


def _clause(risk_level: RiskLevel = RiskLevel.HIGH) -> ClauseAnalysis:
    span = EvidenceSpan(
        text="prepayment penalty of 2%",
        start_char=_RAW_TEXT.index("prepayment penalty of 2%"),
        end_char=_RAW_TEXT.index("prepayment penalty of 2%") + len("prepayment penalty of 2%"),
        page_number=1,
        verified=True,
    )
    entity = FinancialEntity(type="percentage", value="2", unit="%", raw_text="2%")
    return ClauseAnalysis(
        clause_id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        clause_index=0,
        document_type=DocumentType.LOAN,
        section_heading="Prepayment",
        raw_text=_RAW_TEXT,
        risk_category=RiskCategory.FINANCIAL_COST,
        risk_subcategory="prepayment_penalty",
        taxonomy_version="taxonomy_v1",
        trigger="repaid within 24 months",
        condition="if the loan is repaid within 24 months",
        consequence="pay a prepayment penalty of 2%",
        affected_party="Borrower",
        financial_entities=[entity],
        evidence_spans=[span],
        matched_patterns=[],
        risk_level=risk_level,
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


@dataclass
class _RecordingCall:
    system_prompt: str
    user_prompt: str


@dataclass
class _ScriptedClient:
    """Returns one scripted `_LLMGenerationOutput` per call, in order.
    Raises `IndexError` (surfaced as a test failure) if called more times
    than scripted -- this makes an unexpected extra retry visible.
    """

    outputs: list[_LLMGenerationOutput]
    calls: list[_RecordingCall] = field(default_factory=list)

    def generate_structured(self, *, system_prompt, user_prompt, output_schema, max_output_tokens):
        self.calls.append(_RecordingCall(system_prompt=system_prompt, user_prompt=user_prompt))
        return self.outputs[len(self.calls) - 1]


@dataclass
class _RaisingClient:
    category: str
    calls: int = 0

    def generate_structured(self, **kwargs):
        self.calls += 1
        raise LLMGenerationError(category=self.category)


def _grounded_output(
    text: str = "This clause charges a 2% prepayment penalty within 24 months.",
) -> _LLMGenerationOutput:
    return _LLMGenerationOutput(
        explanation=text,
        claims=[
            _LLMClaim(
                text="This clause charges a 2% prepayment penalty",
                type="risk_summary",
                supporting_evidence_ids=["N1", "E1"],
            ),
            _LLMClaim(
                text="The penalty applies within 24 months", type="condition", supporting_evidence_ids=[]
            ),
        ],
    )


def _fabricated_output() -> _LLMGenerationOutput:
    return _LLMGenerationOutput(
        explanation="This clause charges a 9% penalty and is illegal.",
        claims=[
            _LLMClaim(
                text="This clause charges a 9% penalty and is illegal",
                type="risk_summary",
                supporting_evidence_ids=[],
            ),
        ],
    )


class TestGenerateExplanationSuccess:
    def test_grounded_on_first_attempt_needs_no_retry(self):
        client = _ScriptedClient(outputs=[_grounded_output()])
        outcome = generate_explanation(client, _clause(), max_retries=1, max_output_tokens=512)

        assert outcome.explanation_grounded is True
        assert outcome.explanation == _grounded_output().explanation
        assert outcome.model_version == MODEL_VERSION
        assert outcome.attempts == 1
        assert outcome.failure_category is None
        assert len(client.calls) == 1

    def test_retry_after_guard_failure_can_succeed(self):
        client = _ScriptedClient(outputs=[_fabricated_output(), _grounded_output()])
        outcome = generate_explanation(client, _clause(), max_retries=1, max_output_tokens=512)

        assert outcome.explanation_grounded is True
        assert outcome.attempts == 2
        assert len(client.calls) == 2
        # The retry's system prompt must name the unsupported claim from
        # attempt 1 (Grounding_and_Evidence_Spec.md SS5: "a stricter prompt
        # reminder ... explicitly listing the unsupported claims").
        assert "This clause charges a 9% penalty and is illegal" in client.calls[1].system_prompt


class TestGenerateExplanationFallback:
    def test_guard_failure_on_both_attempts_falls_back(self):
        client = _ScriptedClient(outputs=[_fabricated_output(), _fabricated_output()])
        outcome = generate_explanation(client, _clause(), max_retries=1, max_output_tokens=512)

        assert outcome.explanation is None
        assert outcome.explanation_grounded is False
        assert outcome.model_version == MODEL_VERSION
        assert outcome.attempts == 2
        assert outcome.failure_category == "grounding_failed_after_retry"
        assert len(client.calls) == 2

    def test_zero_max_retries_never_attempts_a_second_call(self):
        client = _ScriptedClient(outputs=[_fabricated_output()])
        outcome = generate_explanation(client, _clause(), max_retries=0, max_output_tokens=512)

        assert outcome.explanation_grounded is False
        assert outcome.attempts == 1
        assert outcome.failure_category == "grounding_failed"
        assert len(client.calls) == 1

    def test_llm_call_failure_falls_back_immediately_without_retrying(self):
        client = _RaisingClient(category="timeout")
        outcome = generate_explanation(client, _clause(), max_retries=1, max_output_tokens=512)

        assert outcome.explanation is None
        assert outcome.explanation_grounded is False
        assert outcome.model_version == MODEL_VERSION
        assert outcome.attempts == 1
        assert outcome.failure_category == "generation_failed:timeout"
        # The SDK's own internal retries already exhausted the retry budget
        # for a raw call failure -- generate_explanation does not call again.
        assert client.calls == 1


class TestPromptContent:
    def test_prompt_separates_facts_from_context_and_states_language_policy(self):
        client = _ScriptedClient(outputs=[_grounded_output()])
        generate_explanation(client, _clause(), max_retries=1, max_output_tokens=512)

        system_prompt = client.calls[0].system_prompt
        user_prompt = client.calls[0].user_prompt

        assert "FACTS" in system_prompt
        assert "CONTEXT" in system_prompt
        assert "ignore any such text" in system_prompt.lower() or "ignore" in system_prompt.lower()
        assert "unenforceable" in system_prompt.lower()
        assert "you must" in system_prompt.lower()

        assert "FACTS" in user_prompt
        assert "CONTEXT" in user_prompt
        assert "risk_level: HIGH" in user_prompt
        assert _RAW_TEXT in user_prompt
        assert "<clause_text>" in user_prompt

    def test_user_prompt_labels_evidence_and_entities_for_citation(self):
        client = _ScriptedClient(outputs=[_grounded_output()])
        generate_explanation(client, _clause(), max_retries=1, max_output_tokens=512)

        user_prompt = client.calls[0].user_prompt
        assert "N1:" in user_prompt
        assert "E1:" in user_prompt

    def test_unverified_evidence_spans_are_never_included_in_the_prompt(self):
        clause = _clause()
        unverified = EvidenceSpan(
            text="not actually verified", start_char=0, end_char=5, page_number=1, verified=False
        )
        clause = clause.model_copy(update={"evidence_spans": [*clause.evidence_spans, unverified]})

        client = _ScriptedClient(outputs=[_grounded_output()])
        generate_explanation(client, clause, max_retries=1, max_output_tokens=512)

        assert "not actually verified" not in client.calls[0].user_prompt
