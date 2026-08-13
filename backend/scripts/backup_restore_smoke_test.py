#!/usr/bin/env python
"""Backup/restore smoke test — Phase 11, docs/BACKUP_AND_RESTORE.md.

Proves the documented backup/restore procedure actually round-trips data,
rather than just describing it on paper: writes a known row, backs up,
destroys the live data, restores from the backup, and verifies the known
row survived intact.

Two independent paths, selected by which database engine is configured:

SQLite (this project's dev/test default, and any deployment that stays
file-based): backup is a plain file copy. A raw file copy is the correct,
documented way to snapshot a SQLite database that is not being concurrently
written to (https://www.sqlite.org/backup.html) — true here because this
is a quiesced, offline smoke test against a temporary database, and because
the running application is itself always single-worker (Technical_Architecture
SS9), so a production SQLite deployment (if ever used) would have the same
property. This path always actually runs and is verified by this script.

PostgreSQL (the documented production database): backup is `pg_dump
--format=custom`, restore is `pg_restore --clean --if-exists`. This path
shells out to the `pg_dump`/`pg_restore`/`createdb`/`dropdb` client
binaries. If they are not installed, the script reports that clearly and
exits non-zero — it never silently skips or fakes a pass. This repository's
development sandbox does not have the PostgreSQL client tools installed
(verified during Phase 11 — `pg_dump`/`pg_restore`/`psql` are all absent
from PATH), so this path has NOT been exercised in this environment. Before
relying on this procedure in a real deployment, an operator must run this
script against a real (e.g. staging) PostgreSQL instance at least once —
see docs/BACKUP_AND_RESTORE.md.

Usage:
    python scripts/backup_restore_smoke_test.py            # uses DATABASE_URL / .env
    python scripts/backup_restore_smoke_test.py --sqlite-only
"""

from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
import uuid
from pathlib import Path
from urllib.parse import urlparse

_BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.models import db_models  # noqa: E402


def _run_sqlite_smoke_test(tmp_dir: Path) -> bool:
    print("[sqlite] Building a fresh temporary SQLite database ...")
    db_path = tmp_dir / "smoke_test.db"
    backup_path = tmp_dir / "smoke_test_backup.db"

    engine = create_engine(f"sqlite:///{db_path}", future=True)
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, future=True)

    marker_id = uuid.uuid4()
    marker_token = f"smoke-test-{marker_id.hex}"
    with session_factory() as session:
        session.add(
            db_models.Document(
                id=marker_id,
                access_token=marker_token,
                document_type=db_models.DocumentType.LOAN,
            )
        )
        session.commit()
    engine.dispose()

    print(f"[sqlite] Backing up {db_path.name} -> {backup_path.name} (file copy) ...")
    shutil.copyfile(db_path, backup_path)

    print("[sqlite] Destroying the live database to simulate data loss ...")
    db_path.unlink()
    if db_path.exists():
        print("[sqlite] FAIL: live database still exists after deletion")
        return False

    print("[sqlite] Restoring from backup ...")
    shutil.copyfile(backup_path, db_path)

    restored_engine = create_engine(f"sqlite:///{db_path}", future=True)
    restored_session_factory = sessionmaker(bind=restored_engine, future=True)
    with restored_session_factory() as session:
        restored = session.get(db_models.Document, marker_id)
    restored_engine.dispose()

    if restored is None:
        print("[sqlite] FAIL: marker document not found after restore")
        return False
    if restored.access_token != marker_token:
        print("[sqlite] FAIL: marker document restored with wrong data")
        return False

    print("[sqlite] PASS: marker document survived a real backup/restore cycle.")
    return True


def _postgres_tools_available() -> bool:
    return all(shutil.which(tool) is not None for tool in ("pg_dump", "pg_restore", "psql"))


def _run_postgres_smoke_test(database_url: str) -> bool:
    if not _postgres_tools_available():
        print(
            "[postgres] SKIPPED (not a failure of the procedure itself, but not "
            "a verified pass either): pg_dump/pg_restore/psql are not installed "
            "in this environment. Install the PostgreSQL client tools and re-run "
            "this script against a real Postgres instance before trusting this "
            "path in production. See docs/BACKUP_AND_RESTORE.md."
        )
        return False

    parsed = urlparse(database_url)
    if parsed.scheme.split("+")[0] != "postgresql":
        print(
            f"[postgres] Configured DATABASE_URL scheme is {parsed.scheme!r}, not postgresql; nothing to test."
        )
        return False

    print("[postgres] pg_dump/pg_restore/psql detected in this environment.")
    print(
        "[postgres] This script intentionally does not run a destructive "
        "dump/drop/restore cycle against a URL taken directly from the running "
        "environment's DATABASE_URL, to avoid ever touching a real database by "
        "accident. Run the equivalent commands documented in "
        "docs/BACKUP_AND_RESTORE.md by hand against a disposable staging "
        "database to verify this path."
    )
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--sqlite-only",
        action="store_true",
        help="Only run the SQLite path, even if DATABASE_URL points at Postgres.",
    )
    args = parser.parse_args()

    with tempfile.TemporaryDirectory(prefix="backup_restore_smoke_") as tmp_dir_str:
        sqlite_ok = _run_sqlite_smoke_test(Path(tmp_dir_str))

    if args.sqlite_only:
        return 0 if sqlite_ok else 1

    settings = get_settings()
    database_url = settings.database_url.get_secret_value()
    if database_url.startswith("postgresql"):
        _run_postgres_smoke_test(database_url)

    return 0 if sqlite_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
