"""LLM client wrapper tests — construction and error paths only. The real
`AnthropicLLMClient.generate_structured` is never invoked here (it would
require a live network call); the SDK's own layer is Anthropic's
responsibility, not this codebase's to re-test.
"""

from __future__ import annotations

from app.core.config import Settings
from app.services.llm_client import AnthropicLLMClient, LLMGenerationError, build_llm_client


class TestBuildLlmClient:
    def test_missing_api_key_raises_before_any_network_call(self):
        settings = Settings(environment="test", database_url="sqlite:///:memory:", anthropic_api_key=None)
        try:
            build_llm_client(settings)
        except LLMGenerationError as exc:
            assert exc.category == "missing_api_key"
        else:
            raise AssertionError("expected LLMGenerationError")

    def test_blank_api_key_is_treated_as_missing(self):
        settings = Settings(environment="test", database_url="sqlite:///:memory:", anthropic_api_key="   ")
        try:
            build_llm_client(settings)
        except LLMGenerationError as exc:
            assert exc.category == "missing_api_key"
        else:
            raise AssertionError("expected LLMGenerationError")

    def test_configured_key_builds_a_client_without_a_network_call(self):
        settings = Settings(
            environment="test", database_url="sqlite:///:memory:", anthropic_api_key="sk-ant-test-key"
        )
        client = build_llm_client(settings)
        assert isinstance(client, AnthropicLLMClient)
        assert client.api_key == "sk-ant-test-key"
        assert client.timeout_seconds == settings.generation_timeout_seconds


class TestLLMGenerationError:
    def test_category_is_the_only_thing_carried(self):
        exc = LLMGenerationError(category="refusal")
        assert exc.category == "refusal"
        assert str(exc) == "refusal"
