from __future__ import annotations

import pytest

from app.core.config import Environment, Settings


def test_development_defaults_do_not_require_secrets():
    settings = Settings(environment=Environment.DEVELOPMENT)
    assert settings.anthropic_api_key is None
    assert settings.database_url.get_secret_value().startswith("sqlite")


def test_production_without_secrets_fails_fast():
    with pytest.raises(RuntimeError) as exc_info:
        Settings(
            environment=Environment.PRODUCTION,
            database_url="sqlite:///./dev.db",
            anthropic_api_key=None,
        )
    message = str(exc_info.value)
    assert "ANTHROPIC_API_KEY" in message
    assert "DATABASE_URL" in message
    # The error must name *which* variables are missing, never leak a value.
    assert "sqlite:///./dev.db" not in message


def test_production_with_real_secrets_succeeds():
    settings = Settings(
        environment=Environment.PRODUCTION,
        database_url="postgresql+psycopg://user:pw@localhost:5432/db",
        anthropic_api_key="sk-ant-real-key-value",
    )
    assert settings.is_production


def test_production_rejects_sqlite_even_with_api_key():
    with pytest.raises(RuntimeError, match="DATABASE_URL"):
        Settings(
            environment=Environment.PRODUCTION,
            database_url="sqlite:///./dev.db",
            anthropic_api_key="sk-ant-real-key-value",
        )


def test_invalid_log_level_rejected():
    with pytest.raises(ValueError):
        Settings(log_level="NOT_A_LEVEL")


def test_cors_origins_parsed_as_list():
    settings = Settings(cors_origins_raw="http://a.com, http://b.com")
    assert settings.cors_origins == ["http://a.com", "http://b.com"]


def test_safe_summary_never_contains_secret_values():
    settings = Settings(
        environment=Environment.PRODUCTION,
        database_url="postgresql+psycopg://user:supersecretpassword@localhost/db",
        anthropic_api_key="sk-ant-topsecretvalue",
    )
    summary = settings.safe_summary()
    dumped = repr(summary)
    assert "supersecretpassword" not in dumped
    assert "sk-ant-topsecretvalue" not in dumped
    assert summary["anthropic_api_key_configured"] is True


def test_settings_repr_masks_secrets():
    settings = Settings(anthropic_api_key="sk-ant-shouldnotappear")
    assert "sk-ant-shouldnotappear" not in repr(settings)
    assert "sk-ant-shouldnotappear" not in str(settings)


def test_retrieval_settings_have_sane_defaults():
    settings = Settings()
    assert settings.retrieval_top_k == 5  # AI_Risk_Engine_Design.md SS2 "top-k=5"
    assert settings.embedding_model_name
    assert 0.0 <= settings.retrieval_min_similarity_floor <= 1.0
    assert 0.0 <= settings.retrieval_min_lexical_floor <= 1.0
    assert settings.taxonomy_version == "taxonomy_v1"
    assert settings.corpus_version


def test_retrieval_settings_are_overridable():
    settings = Settings(retrieval_top_k=3, taxonomy_version="taxonomy_v2")
    assert settings.retrieval_top_k == 3
    assert settings.taxonomy_version == "taxonomy_v2"
