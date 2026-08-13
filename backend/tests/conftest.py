"""Shared pytest fixtures.

Tests never touch real financial documents — all clause/entity/evidence text
used here is synthetic and clearly fictional.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.orm import Session

os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from app.core.config import Settings  # noqa: E402
from app.core.config import get_settings as real_get_settings  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.db.session import create_db_engine, create_session_factory  # noqa: E402
from app.db.session import get_db as real_get_db  # noqa: E402
from app.db.session import get_session_factory as real_get_session_factory  # noqa: E402
from app.main import app  # noqa: E402
from app.models import db_models  # noqa: E402,F401


@pytest.fixture()
def settings() -> Settings:
    return Settings(environment="test", database_url="sqlite:///:memory:")


@pytest.fixture()
def engine(settings: Settings) -> Iterator[Engine]:
    eng = create_db_engine(settings)
    Base.metadata.create_all(eng)
    yield eng
    Base.metadata.drop_all(eng)
    eng.dispose()


@pytest.fixture()
def db_session(engine: Engine) -> Iterator[Session]:
    session_factory = create_session_factory(engine)
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


def make_document(**overrides) -> db_models.Document:
    defaults = dict(
        id=uuid.uuid4(),
        access_token=uuid.uuid4().hex,
        document_type=db_models.DocumentType.LOAN,
    )
    defaults.update(overrides)
    return db_models.Document(**defaults)


def make_clause(document_id: uuid.UUID, **overrides) -> db_models.Clause:
    defaults = dict(
        id=uuid.uuid4(),
        document_id=document_id,
        clause_index=0,
        raw_text="Synthetic clause text for testing purposes only.",
    )
    defaults.update(overrides)
    return db_models.Clause(**defaults)


def make_clause_analysis(clause_id: uuid.UUID, **overrides) -> db_models.ClauseAnalysisORM:
    defaults = dict(
        id=uuid.uuid4(),
        clause_id=clause_id,
        taxonomy_version="taxonomy_v1",
        risk_level=db_models.RiskLevel.LOW,
        risk_score=0.1,
        confidence_level=db_models.ConfidenceLevel.MEDIUM,
        confidence_score=0.5,
        abstained=False,
        model_version="gen-v0",
        engine_version="engine-v0",
    )
    defaults.update(overrides)
    return db_models.ClauseAnalysisORM(**defaults)


def make_corpus_pattern(**overrides) -> db_models.CorpusPattern:
    defaults = dict(
        id=uuid.uuid4(),
        pattern_text="Synthetic corpus pattern text for testing purposes only.",
        taxonomy_version="taxonomy_v1",
        corpus_version="corpus_v1",
        is_negative_example=False,
    )
    defaults.update(overrides)
    return db_models.CorpusPattern(**defaults)


@pytest.fixture(scope="session")
def embedding_service():
    """Session-scoped — the sentence-transformers model is loaded once
    (~seconds) and reused across every test that needs it, matching Phase 4
    spec SS8/SS22 ("model loaded once ... no model loading on every
    clause") applied to the test suite itself."""
    from app.services.embedding_service import EmbeddingService

    return EmbeddingService()


@pytest.fixture()
def vector_store():
    """Fresh in-memory (non-persistent) Chroma client per test — collection
    names are keyed by (taxonomy_version, corpus_version), so reusing one
    client across tests using the same version strings would leak indexed
    patterns between otherwise-independent tests."""
    from app.services.retrieval.vector_store import ChromaVectorStore, create_client

    return ChromaVectorStore(create_client(None))


@pytest.fixture()
def utcnow() -> datetime:
    return datetime.now(UTC)


@pytest.fixture()
def make_client(
    db_session: Session,
    engine: Engine,
    embedding_service,
    vector_store,
    tmp_path,
) -> Iterator[Callable[..., TestClient]]:
    """Factory fixture for a `TestClient` wired to the real app with the DB
    dependency overridden to the test's in-memory session and the settings
    dependency overridden to an isolated `tmp_path` upload directory.

    Also overrides `get_session_factory`/`get_embedding_service`/
    `get_vector_store` (Phase 8): `POST /documents` schedules a
    `BackgroundTasks` pipeline run that opens its own session, resolved
    *at request time* -- without this override it would build a real
    `EmbeddingService` (slow model load) and a real disk-persisted
    `ChromaVectorStore` (default `chroma_persist_dir`), and a session bound
    to a throwaway `sqlite:///:memory:` engine the test's own `db_session`
    never sees. `create_session_factory(engine)` reuses this test's own
    `StaticPool`-backed engine so the background task's fresh session sees
    exactly the same in-memory database `db_session` does.

    Each call accepts `Settings` field overrides (e.g. `max_pdf_pages=1`) so
    individual tests can exercise limits without a shared global config.
    """
    from app.api.deps import get_embedding_service as real_get_embedding_service
    from app.api.deps import get_vector_store as real_get_vector_store

    def make(**settings_overrides: Any) -> TestClient:
        settings = Settings(
            environment="test",
            database_url="sqlite:///:memory:",
            upload_dir=str(tmp_path / "uploads"),
            **settings_overrides,
        )

        def override_get_db() -> Iterator[Session]:
            yield db_session
            db_session.commit()

        def override_get_settings() -> Settings:
            return settings

        app.dependency_overrides[real_get_db] = override_get_db
        app.dependency_overrides[real_get_settings] = override_get_settings
        app.dependency_overrides[real_get_session_factory] = lambda: create_session_factory(engine)
        app.dependency_overrides[real_get_embedding_service] = lambda: embedding_service
        app.dependency_overrides[real_get_vector_store] = lambda: vector_store
        return TestClient(app)

    yield make
    app.dependency_overrides.clear()
