"""Mockable Anthropic client wrapper — Phase 7 spec ("mocked LLM provider
testing (no live calls in unit tests)").

Every direct `anthropic` SDK call is isolated behind `GenerationLLMClient`
(a `Protocol`) so `generation_service.py` never imports the SDK directly and
every unit test substitutes a fake implementation. `AnthropicLLMClient` is
the only real implementation; it is never constructed or called from the
automated test suite.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, TypeVar

from pydantic import BaseModel

from app.core.config import Settings
from app.services.generation_config import GENERATION_MODEL_ID

_SchemaT = TypeVar("_SchemaT", bound=BaseModel)


class LLMGenerationError(Exception):
    """Raised for any failure calling the LLM provider — timeout, API error,
    refusal, or schema-validation failure. `generation_service.py` treats
    every subtype identically (one retry, then the safe fallback state —
    Grounding_and_Evidence_Spec.md SS5). `category` is a short machine label
    safe to log (Security_and_Privacy_v2.md SS6) — never an interpolated
    message, which could incidentally carry clause content from the SDK's
    own exception string.
    """

    def __init__(self, category: str) -> None:
        self.category = category
        super().__init__(category)


class GenerationLLMClient(Protocol):
    def generate_structured(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        output_schema: type[_SchemaT],
        max_output_tokens: int,
    ) -> _SchemaT:
        """Returns a validated instance of `output_schema`. Raises
        `LLMGenerationError` on any failure — never returns partial or
        unvalidated output."""
        ...


@dataclass(frozen=True, slots=True)
class AnthropicLLMClient:
    """Real implementation, backed by the Messages API structured-output
    feature (`client.messages.parse` + `output_format=<PydanticModel>`),
    which guarantees schema-valid JSON without a bespoke parse-and-retry
    loop of our own.
    """

    api_key: str
    timeout_seconds: float
    model: str = GENERATION_MODEL_ID

    def generate_structured(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        output_schema: type[_SchemaT],
        max_output_tokens: int,
    ) -> _SchemaT:
        import anthropic  # local import: keeps the SDK dependency out of any

        # module that only needs the Protocol (tests, callers) — the real
        # client is constructed only here, at the moment of an actual call.
        client = anthropic.Anthropic(api_key=self.api_key, timeout=self.timeout_seconds)
        try:
            response = client.messages.parse(
                model=self.model,
                max_tokens=max_output_tokens,
                system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}],
                output_format=output_schema,
            )
        except anthropic.AnthropicError as exc:
            # Base class for every SDK-raised exception (API errors, rate
            # limits, connection/timeout failures) — `category` carries only
            # the exception's type name, never `str(exc)`, which could
            # incidentally echo request content (Security_and_Privacy_v2.md
            # SS6).
            raise LLMGenerationError(category=type(exc).__name__) from None

        if response.stop_reason == "refusal":
            raise LLMGenerationError(category="refusal")
        if response.parsed_output is None:
            raise LLMGenerationError(category="unparsable_output")
        return response.parsed_output


def build_llm_client(settings: Settings) -> GenerationLLMClient:
    """Constructs the real client from application settings. Raises
    `LLMGenerationError` immediately if no API key is configured, rather
    than deferring to a confusing failure inside the SDK call — mirrors
    `Settings._validate_production_requirements`'s fail-fast philosophy
    (though this check is per-call, not startup, since the key is optional
    outside production).
    """
    if settings.anthropic_api_key is None or not settings.anthropic_api_key.get_secret_value().strip():
        raise LLMGenerationError(category="missing_api_key")
    return AnthropicLLMClient(
        api_key=settings.anthropic_api_key.get_secret_value(),
        timeout_seconds=settings.generation_timeout_seconds,
    )
