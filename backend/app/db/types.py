"""Backend-agnostic UUID column type.

Production runs on PostgreSQL (Technical_Architecture_v2.md SS10), which has
a native UUID type. Phase 0 tests run against SQLite (no local PostgreSQL
instance is assumed to be available for a foundation-only phase), which has
no native UUID type. `GUID` stores a native `UUID` on PostgreSQL and a
36-character string on any other dialect, so the same model definitions and
Alembic migration work unchanged against both — this is the standard
SQLAlchemy "platform independent GUID" recipe.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.dialects.postgresql import UUID as PostgresUUID
from sqlalchemy.types import CHAR, TypeDecorator


class GUID(TypeDecorator):
    impl = CHAR
    cache_ok = True

    def load_dialect_impl(self, dialect: Any) -> Any:
        if dialect.name == "postgresql":
            return dialect.type_descriptor(PostgresUUID(as_uuid=True))
        return dialect.type_descriptor(CHAR(36))

    def process_bind_param(self, value: Any, dialect: Any) -> Any:
        if value is None:
            return value
        if not isinstance(value, uuid.UUID):
            value = uuid.UUID(str(value))
        if dialect.name == "postgresql":
            return value
        return str(value)

    def process_result_value(self, value: Any, dialect: Any) -> uuid.UUID | None:
        if value is None:
            return value
        if isinstance(value, uuid.UUID):
            return value
        return uuid.UUID(value)
