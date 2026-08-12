"""Application configuration.

Loaded once from environment variables / `.env` via pydantic-settings.
Per Security_and_Privacy_v2.md SS5: secrets live only in backend environment
variables and must never be logged or printed. This module never logs the
`Settings` instance itself; secret-shaped fields are typed as `SecretStr` so
an accidental `print(settings)` or `repr(settings)` masks the value.
"""

from __future__ import annotations

from enum import Enum

from pydantic import SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Environment(str, Enum):
    DEVELOPMENT = "development"
    TEST = "test"
    PRODUCTION = "production"


class Settings(BaseSettings):
    """Backend configuration.

    Fails fast (raises at startup, not at first use) when required
    production secrets are missing — see `_validate_production_requirements`.
    Never printed or logged in full; use `safe_summary()` for diagnostics.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    environment: Environment = Environment.DEVELOPMENT

    # Development-only default. Production must set a real PostgreSQL URL.
    database_url: SecretStr = SecretStr("sqlite:///./dev.db")

    # Anthropic API key for the Generation Service. Optional outside of
    # production so the schema/DB foundation (Phase 0) can be developed and
    # tested without a real key.
    anthropic_api_key: SecretStr | None = None

    cors_origins_raw: str = "http://localhost:3000"

    log_level: str = "INFO"

    @field_validator("log_level")
    @classmethod
    def _validate_log_level(cls, value: str) -> str:
        normalized = value.upper()
        allowed = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        if normalized not in allowed:
            raise ValueError(f"log_level must be one of {sorted(allowed)}, got {value!r}")
        return normalized

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins_raw.split(",") if origin.strip()]

    @property
    def is_production(self) -> bool:
        return self.environment is Environment.PRODUCTION

    @model_validator(mode="after")
    def _validate_production_requirements(self) -> Settings:
        """Fail safely (loud, immediate, no silent defaults) when running in
        production without the secrets the rest of the system assumes exist.

        This never includes the actual secret value in the raised error —
        only the name of the missing variable.
        """
        if not self.is_production:
            return self

        missing: list[str] = []

        if self.anthropic_api_key is None or not self.anthropic_api_key.get_secret_value().strip():
            missing.append("ANTHROPIC_API_KEY")

        db_url = self.database_url.get_secret_value()
        if db_url.startswith("sqlite"):
            missing.append("DATABASE_URL (must be a real PostgreSQL URL in production, not sqlite)")

        if missing:
            joined = ", ".join(missing)
            raise RuntimeError(
                "Missing or invalid required production configuration: "
                f"{joined}. Set these environment variables before starting "
                "the application in production."
            )

        return self

    def safe_summary(self) -> dict[str, object]:
        """Diagnostic snapshot safe to log or print — never includes secret values."""
        return {
            "environment": self.environment.value,
            "database_configured": bool(self.database_url.get_secret_value()),
            "database_is_sqlite": self.database_url.get_secret_value().startswith("sqlite"),
            "anthropic_api_key_configured": self.anthropic_api_key is not None
            and bool(self.anthropic_api_key.get_secret_value().strip()),
            "cors_origins": self.cors_origins,
            "log_level": self.log_level,
        }


def get_settings() -> Settings:
    """Construct `Settings` from the environment.

    Not cached at module import time so tests can freely construct
    `Settings` with different environment overrides without process-wide
    caching surprises. FastAPI dependency callers may wrap this with
    `functools.lru_cache` at the call site if desired.
    """
    return Settings()
