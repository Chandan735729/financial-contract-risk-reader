"""Database engine/session construction.

Never logs the connection string (it may embed a password) — only a boolean
"configured" flag via `Settings.safe_summary()` should ever be logged.
"""

from __future__ import annotations

from collections.abc import Generator
from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import Settings, get_settings


def create_db_engine(settings: Settings) -> Engine:
    db_url = settings.database_url.get_secret_value()
    is_sqlite = db_url.startswith("sqlite")
    kwargs: dict = {}
    if is_sqlite:
        # `check_same_thread=False` alone is not enough for `sqlite:///:memory:`:
        # SQLAlchemy's default pool for an in-memory DB is one connection
        # *per thread* (SingletonThreadPool), and a `:memory:` database is
        # private to its connection — so a request handled on a different
        # thread (e.g. FastAPI's TestClient, which runs the app in an anyio
        # worker thread) would silently see an empty, table-less database.
        # StaticPool pins the engine to exactly one connection, shared by
        # every thread, so app code and test assertions see the same data.
        kwargs["connect_args"] = {"check_same_thread": False}
        kwargs["poolclass"] = StaticPool
    return create_engine(db_url, future=True, **kwargs)


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def get_db_session(session_factory: sessionmaker[Session]) -> Generator[Session, None, None]:
    """FastAPI-dependency-shaped generator: yields a session, always closes it."""
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


@lru_cache
def _process_session_factory() -> sessionmaker[Session]:
    # Process-global engine/session-factory singleton for the running app —
    # built once from `get_settings()` at first use. Tests never go through
    # this path: they override the `get_db` FastAPI dependency directly
    # (see tests/conftest.py) rather than relying on real environment
    # variables and a cached singleton.
    return create_session_factory(create_db_engine(get_settings()))


def get_db() -> Generator[Session, None, None]:
    """The app's real `Depends(get_db)` — commits on success, rolls back and
    re-raises on any exception, always closes. Endpoints must not commit or
    close the session themselves.
    """
    session = _process_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_session_factory() -> sessionmaker[Session]:
    """`Depends(get_session_factory)` — for the rare caller (Phase 8's
    background pipeline task) that needs to open its *own* session outside
    the request/response cycle, rather than reusing the request-scoped
    session `get_db` yields.

    This matters specifically for `BackgroundTasks`: Starlette runs them
    only *after* the response has been sent, which is after `get_db`'s
    `finally: session.close()` has already executed — the request's
    session is gone by then, so a background task must open a fresh one
    from the same engine. Exposed as its own dependency (not just called
    directly) so tests can override it to point at the same
    `StaticPool`-backed test engine `db_session` uses, exactly like `get_db`
    is overridden (see `tests/conftest.py`).
    """
    return _process_session_factory()
