"""Database engine/session construction.

Never logs the connection string (it may embed a password) — only a boolean
"configured" flag via `Settings.safe_summary()` should ever be logged.
"""

from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings


def create_db_engine(settings: Settings) -> Engine:
    db_url = settings.database_url.get_secret_value()
    connect_args = {"check_same_thread": False} if db_url.startswith("sqlite") else {}
    return create_engine(db_url, connect_args=connect_args, future=True)


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def get_db_session(session_factory: sessionmaker[Session]) -> Generator[Session, None, None]:
    """FastAPI-dependency-shaped generator: yields a session, always closes it."""
    session = session_factory()
    try:
        yield session
    finally:
        session.close()
