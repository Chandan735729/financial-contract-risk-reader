"""Alembic migration up/down test — Implementation_Roadmap.md Phase 0.

Runs the real `alembic` CLI (as an external process, matching how it would
actually be invoked) against a throwaway SQLite file, so the test exercises
the actual migration script rather than just the ORM models.
"""

from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]

EXPECTED_TABLES = {
    "users",
    "documents",
    "clauses",
    "clause_analyses",
    "financial_entities",
    "evidence_spans",
    "matched_patterns",
    "corpus_patterns",
    "processing_jobs",
}


def _table_names(db_path: Path) -> set[str]:
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        return {row[0] for row in cursor.fetchall()}
    finally:
        conn.close()


def _run_alembic(*args: str, env: dict) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=BACKEND_DIR,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_migration_upgrade_creates_all_tables_and_downgrade_removes_them(tmp_path):
    db_path = tmp_path / "migration_test.db"
    env = {**os.environ, "ENVIRONMENT": "development", "DATABASE_URL": f"sqlite:///{db_path}"}

    upgrade = _run_alembic("upgrade", "head", env=env)
    assert upgrade.returncode == 0, upgrade.stderr

    tables = _table_names(db_path)
    assert EXPECTED_TABLES.issubset(tables)

    downgrade = _run_alembic("downgrade", "base", env=env)
    assert downgrade.returncode == 0, downgrade.stderr

    tables_after = _table_names(db_path)
    assert tables_after.isdisjoint(EXPECTED_TABLES)
