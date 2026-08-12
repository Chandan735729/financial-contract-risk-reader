"""Shared pytest fixtures.

Tests never touch real financial documents — all clause/entity/evidence text
used here is synthetic and clearly fictional.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import Session

os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from app.core.config import Settings  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.db.session import create_db_engine, create_session_factory  # noqa: E402
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


@pytest.fixture()
def utcnow() -> datetime:
    return datetime.now(UTC)
