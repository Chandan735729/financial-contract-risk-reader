"""Generation pipeline orchestration tests — exercises
`generate_pending_explanations` against the real `clause_analyses` schema,
continuing Phase 5's persistence pattern
(tests/services/test_risk_scoring_service.py). Every test injects a fake
`GenerationLLMClient` -- no live Anthropic call is ever made.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from app.models import db_models
from app.models.enums import DocumentType, RiskLevel
from app.services.generation_config import GENERATION_SKIPPED_MODEL_VERSION, MODEL_VERSION
from app.services.generation_pipeline_service import generate_pending_explanations
from app.services.generation_service import _LLMClaim, _LLMGenerationOutput
from app.services.llm_client import LLMGenerationError
from tests.conftest import make_clause, make_clause_analysis, make_document

_RAW_TEXT = (
    "The Borrower shall pay a prepayment penalty of 2% of the outstanding "
    "principal if the loan is repaid in full within 24 months of the "
    "disbursement date."
)


def _grounded_output() -> _LLMGenerationOutput:
    return _LLMGenerationOutput(
        explanation="This clause charges a 2% prepayment penalty within 24 months.",
        claims=[
            _LLMClaim(
                text="This clause charges a 2% prepayment penalty",
                type="risk_summary",
                supporting_evidence_ids=[],
            ),
        ],
    )


def _fabricated_output() -> _LLMGenerationOutput:
    return _LLMGenerationOutput(
        explanation="This clause charges a $99,999 penalty.",
        claims=[
            _LLMClaim(
                text="This clause charges a $99,999 penalty", type="risk_summary", supporting_evidence_ids=[]
            ),
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
class _AlwaysGroundedClient:
    call_count: int = 0

    def generate_structured(self, *, system_prompt, user_prompt, output_schema, max_output_tokens):
        self.call_count += 1
        return _grounded_output()


@dataclass
class _RaisingClient:
    calls: int = 0

    def generate_structured(self, **kwargs):
        self.calls += 1
        raise LLMGenerationError(category="overloaded")


def _seed_clause(
    db_session, *, risk_level: RiskLevel, verified_evidence: bool = True, document=None
) -> tuple[db_models.Document, db_models.Clause, db_models.ClauseAnalysisORM]:
    document = document or make_document()
    db_session.add(document)
    db_session.flush()

    clause = make_clause(document_id=document.id, raw_text=_RAW_TEXT)
    db_session.add(clause)
    db_session.flush()

    analysis = make_clause_analysis(
        clause_id=clause.id,
        risk_level=risk_level,
        risk_score=0.81 if risk_level == RiskLevel.HIGH else 0.5,
        confidence_level=db_models.ConfidenceLevel.HIGH,
        confidence_score=0.9,
        abstained=risk_level == RiskLevel.UNKNOWN,
        abstain_reason="insufficient signal" if risk_level == RiskLevel.UNKNOWN else None,
        model_version="unscored",
    )
    db_session.add(analysis)
    db_session.flush()

    if verified_evidence and risk_level in (RiskLevel.HIGH, RiskLevel.MEDIUM):
        span_text = "prepayment penalty of 2%"
        span = db_models.EvidenceSpan(
            id=uuid.uuid4(),
            clause_analysis_id=analysis.id,
            text=span_text,
            start_char=_RAW_TEXT.index(span_text),
            end_char=_RAW_TEXT.index(span_text) + len(span_text),
            page_number=1,
            verified=True,
        )
        db_session.add(span)
        db_session.flush()

    db_session.commit()
    return document, clause, analysis


class TestEligibility:
    def test_high_risk_clause_is_generated_and_grounded(self, db_session, settings):
        document, clause, analysis = _seed_clause(db_session, risk_level=RiskLevel.HIGH)
        client = _AlwaysGroundedClient()

        summary = generate_pending_explanations(
            db_session, document.id, document_type=DocumentType.LOAN, settings=settings, client=client
        )
        db_session.commit()

        db_session.refresh(analysis)
        assert summary.eligible == 1
        assert summary.grounded == 1
        assert analysis.explanation_grounded is True
        assert analysis.explanation is not None
        assert analysis.model_version == MODEL_VERSION
        assert client.call_count == 1

    def test_medium_risk_clause_is_generated(self, db_session, settings):
        document, clause, analysis = _seed_clause(db_session, risk_level=RiskLevel.MEDIUM)
        client = _AlwaysGroundedClient()

        summary = generate_pending_explanations(
            db_session, document.id, document_type=DocumentType.LOAN, settings=settings, client=client
        )

        assert summary.eligible == 1
        assert summary.grounded == 1
        assert client.call_count == 1

    def test_low_risk_clause_is_skipped_not_generated(self, db_session, settings):
        document, clause, analysis = _seed_clause(
            db_session, risk_level=RiskLevel.LOW, verified_evidence=False
        )
        client = _AlwaysGroundedClient()

        summary = generate_pending_explanations(
            db_session, document.id, document_type=DocumentType.LOAN, settings=settings, client=client
        )
        db_session.commit()

        db_session.refresh(analysis)
        assert summary.eligible == 0
        assert summary.skipped_ineligible_risk_level == 1
        assert client.call_count == 0
        assert analysis.explanation is None
        assert analysis.explanation_grounded is None
        assert analysis.model_version == GENERATION_SKIPPED_MODEL_VERSION

    def test_unknown_abstained_clause_is_skipped_not_generated(self, db_session, settings):
        document, clause, analysis = _seed_clause(
            db_session, risk_level=RiskLevel.UNKNOWN, verified_evidence=False
        )
        client = _AlwaysGroundedClient()

        summary = generate_pending_explanations(
            db_session, document.id, document_type=DocumentType.LOAN, settings=settings, client=client
        )
        db_session.commit()

        db_session.refresh(analysis)
        assert summary.skipped_ineligible_risk_level == 1
        assert client.call_count == 0
        assert analysis.model_version == GENERATION_SKIPPED_MODEL_VERSION

    def test_mixed_document_only_calls_the_llm_for_eligible_clauses(self, db_session, settings):
        document = make_document()
        db_session.add(document)
        db_session.flush()
        _seed_clause(db_session, risk_level=RiskLevel.HIGH, document=document)
        _seed_clause(db_session, risk_level=RiskLevel.LOW, verified_evidence=False, document=document)
        _seed_clause(db_session, risk_level=RiskLevel.MEDIUM, document=document)

        client = _AlwaysGroundedClient()
        summary = generate_pending_explanations(
            db_session, document.id, document_type=DocumentType.LOAN, settings=settings, client=client
        )

        assert summary.total_clauses == 3
        assert summary.eligible == 2
        assert summary.skipped_ineligible_risk_level == 1
        assert client.call_count == 2


class TestFallback:
    def test_grounding_failure_after_retry_persists_the_fallback_state(self, db_session, settings):
        document, clause, analysis = _seed_clause(db_session, risk_level=RiskLevel.HIGH)
        client = _ScriptedClient(outputs=[_fabricated_output(), _fabricated_output()])

        summary = generate_pending_explanations(
            db_session, document.id, document_type=DocumentType.LOAN, settings=settings, client=client
        )
        db_session.commit()

        db_session.refresh(analysis)
        assert summary.fallback == 1
        assert summary.grounded == 0
        assert analysis.explanation is None
        assert analysis.explanation_grounded is False
        assert analysis.model_version == MODEL_VERSION
        assert client.call_count == 2


class TestCostControl:
    def test_per_document_call_cap_skips_remaining_eligible_clauses(self, db_session, settings):
        document = make_document()
        db_session.add(document)
        db_session.flush()
        _, _, analysis_a = _seed_clause(db_session, risk_level=RiskLevel.HIGH, document=document)
        _, _, analysis_b = _seed_clause(db_session, risk_level=RiskLevel.HIGH, document=document)

        capped_settings = settings.model_copy(update={"generation_max_calls_per_document": 1})
        client = _AlwaysGroundedClient()

        summary = generate_pending_explanations(
            db_session, document.id, document_type=DocumentType.LOAN, settings=capped_settings, client=client
        )
        db_session.commit()

        assert summary.eligible == 2
        assert client.call_count == 1
        assert summary.grounded == 1
        assert summary.skipped_cost_cap == 1

        db_session.refresh(analysis_a)
        db_session.refresh(analysis_b)
        skipped_analyses = [
            a for a in (analysis_a, analysis_b) if a.model_version == GENERATION_SKIPPED_MODEL_VERSION
        ]
        assert len(skipped_analyses) == 1


class TestIsolation:
    def test_one_clauses_llm_failure_does_not_affect_a_sibling_clause(self, db_session, settings):
        document = make_document()
        db_session.add(document)
        db_session.flush()
        _, clause_a, analysis_a = _seed_clause(db_session, risk_level=RiskLevel.HIGH, document=document)
        _, clause_b, analysis_b = _seed_clause(db_session, risk_level=RiskLevel.HIGH, document=document)

        class _CrashFirstThenSucceed:
            """Raises an exception `generate_explanation` does not itself
            catch (unlike `LLMGenerationError`, which it handles internally
            as a fallback outcome) -- this simulates an unexpected pipeline
            crash, the case the outer per-clause SAVEPOINT exists for.
            """

            def __init__(self):
                self.call_count = 0

            def generate_structured(self, **kwargs):
                self.call_count += 1
                if self.call_count == 1:
                    raise RuntimeError("unexpected pipeline crash")
                return _grounded_output()

        client = _CrashFirstThenSucceed()
        summary = generate_pending_explanations(
            db_session, document.id, document_type=DocumentType.LOAN, settings=settings, client=client
        )
        db_session.commit()

        assert summary.failed == 1
        assert summary.grounded == 1

        db_session.refresh(analysis_a)
        db_session.refresh(analysis_b)
        grounded_states = [a.explanation_grounded for a in (analysis_a, analysis_b)]
        # The crashed clause's SAVEPOINT rolled back entirely, so its row is
        # untouched (still its pre-attempt None); the other succeeded.
        assert True in grounded_states
        assert None in grounded_states
