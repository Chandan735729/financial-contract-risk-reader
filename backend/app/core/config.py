"""Application configuration.

Loaded once from environment variables / `.env` via pydantic-settings.
Per Security_and_Privacy_v2.md SS5: secrets live only in backend environment
variables and must never be logged or printed. This module never logs the
`Settings` instance itself; secret-shaped fields are typed as `SecretStr` so
an accidental `print(settings)` or `repr(settings)` masks the value.
"""

from __future__ import annotations

from enum import Enum

from pydantic import Field, SecretStr, field_validator, model_validator
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
        # `cors_origins_raw` below sets a `validation_alias` -- without
        # this, pydantic would only accept construction via that alias,
        # breaking every existing direct `Settings(cors_origins_raw=...)`
        # call (tests, mainly). With it, both the Python field name and
        # the alias work for direct construction; env-var loading still
        # uses the alias as the actual variable name either way.
        populate_by_name=True,
    )

    environment: Environment = Environment.DEVELOPMENT

    # Development-only default. Production must set a real PostgreSQL URL.
    database_url: SecretStr = SecretStr("sqlite:///./dev.db")

    # Anthropic API key for the Generation Service. Optional outside of
    # production so the schema/DB foundation (Phase 0) can be developed and
    # tested without a real key.
    anthropic_api_key: SecretStr | None = None

    # Phase 11 production-config review: the field is internally named
    # `_raw` (unparsed) because `cors_origins` below is the parsed
    # `list[str]` property callers actually use, but the natural env var
    # name an operator would type is `CORS_ORIGINS`, not `CORS_ORIGINS_RAW`
    # -- pydantic-settings would otherwise only recognize the latter,
    # silently ignoring `CORS_ORIGINS` and leaving CORS on the
    # localhost-only default with no error. `validation_alias` closes that
    # gap: `CORS_ORIGINS` is the actual, documented, working env var name.
    cors_origins_raw: str = Field(default="http://localhost:3000", validation_alias="CORS_ORIGINS")

    log_level: str = "INFO"

    # Upload / parsing limits (Phase 2 — Security_and_Privacy_v2.md SS1 "Resource
    # exhaustion / cost abuse", SS8 abuse protection). Deliberately conservative
    # defaults for a laptop-buildable MVP; tunable per deployment via env vars.
    max_upload_size_bytes: int = 20 * 1024 * 1024  # 20 MB
    max_pdf_pages: int = 200
    # DOCX has no native "page" concept (rendering-dependent) — paragraph count
    # is the practical proxy cap for this file format. See PROVISIONAL_DECISIONS.md.
    max_docx_paragraphs: int = 5000
    # Below this total extracted character count, a parse is treated as
    # LOW_TEXT_CONTENT regardless of page/paragraph count (empty or near-empty).
    min_text_chars: int = 200
    # Below this average characters-per-page, a multi-page parse is treated as
    # LOW_TEXT_CONTENT even if the absolute total clears `min_text_chars` —
    # catches scanned/image-only PDFs with a few OCR-stray characters per page.
    min_avg_chars_per_page: float = 20.0

    # Local-filesystem MVP storage root for uploaded originals — see
    # PROVISIONAL_DECISIONS.md "Phase 2: uploaded document storage strategy".
    # Never served directly or exposed via any API response.
    upload_dir: str = "./data/uploads"

    # Clause Understanding / Retrieval (Phase 4 — AI_Risk_Engine_Design.md SS2).
    # sentence-transformers model — runs locally, no external API call, no
    # fine-tuning (Phase 4 spec SS8/SS10). "all-MiniLM-L6-v2" is the standard
    # small/fast choice for a laptop-buildable MVP.
    embedding_model_name: str = "sentence-transformers/all-MiniLM-L6-v2"
    # AI_Risk_Engine_Design.md SS2: "top-k=5" — a named, versionable setting,
    # never hardcoded at call sites (Phase 4 spec SS4).
    retrieval_top_k: int = 5
    # Below this raw cosine similarity / BM25 score, a candidate is not even
    # considered — "a floor for candidate consideration, not a decision
    # threshold" (AI_Risk_Engine_Design.md SS2).
    retrieval_min_similarity_floor: float = 0.3
    retrieval_min_lexical_floor: float = 0.1
    # The taxonomy/corpus version this running system expects to score
    # against — retrieval only ever considers corpus_patterns matching both
    # (AI_Risk_Engine_Design.md SS2 "Corpus versioning"; SS7 "Corpus/taxonomy
    # version mismatch ... halts scoring"). See Risk_Taxonomy_and_Labeling_Spec.md.
    taxonomy_version: str = "taxonomy_v1"
    corpus_version: str = "corpus_v1"
    # Local persistence directory for the Chroma vector store — same
    # local-filesystem-MVP precedent as `upload_dir` (PROVISIONAL_DECISIONS.md
    # "Phase 2: uploaded document storage strategy"). Never holds per-user
    # document embeddings, only the permanent labeled corpus
    # (Technical_Architecture_v2.md SS6).
    chroma_persist_dir: str = "./data/chroma"

    # Generation Service / Grounding Guard (Grounding_and_Evidence_Spec.md,
    # Security_and_Privacy_v2.md SS8 "Per-document caps ... to bound cost and
    # prevent a single adversarial document from consuming disproportionate
    # resources"). The model ID and prompt version are versioned code
    # constants (`generation_config.py`), not env-tunable, so every
    # `model_version` value on a persisted `clause_analyses` row is
    # reproducible from source — same rationale as `RISK_ENGINE_VERSION`
    # being a code constant rather than a setting.
    generation_max_retries: int = 1
    generation_max_calls_per_document: int = 60
    generation_timeout_seconds: float = 30.0
    generation_max_output_tokens: int = 1024

    # Upload rate limiting (Phase 10 — Security_and_Privacy_v2.md SS8:
    # "Upload rate limiting per session/IP", required since the original
    # v1 doc but never implemented until this phase; see
    # docs/PROVISIONAL_DECISIONS.md "Phase 10: upload rate limiting"). A
    # deliberately simple in-process fixed-window counter, not a new
    # external dependency — consistent with this project's established
    # MVP in-process precedent (Technical_Architecture_v2.md SS9).
    upload_rate_limit_max_requests: int = 20
    upload_rate_limit_window_seconds: float = 60.0

    # Trusted-proxy IP resolution for the rate limiter (Phase 11 —
    # docs/SECURITY_AUDIT.md SS5's documented limitation, closed here).
    # `X-Forwarded-For` is attacker-controlled input and must never be
    # honored unless a deployment explicitly configures a trusted proxy —
    # see `app/core/rate_limit.py::resolve_client_ip`. Default `False`
    # (direct-connection IP only) is the safe MVP default; a real
    # deployment behind a reverse proxy sets this explicitly.
    trust_proxy_headers: bool = False

    # Automatic retention (Phase 11 — Security_and_Privacy_v2.md SS3:
    # "Automatic retention window (e.g., 90 days)"). Applies to documents
    # and everything that cascades from them; corpus/reference data is a
    # separate, permanent asset never touched by this setting (see
    # `app/services/retention_service.py`).
    document_retention_days: int = 90

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
