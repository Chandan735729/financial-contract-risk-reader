#!/usr/bin/env python
"""Standalone entry point for the automatic retention cleanup job — Phase
11, Security_and_Privacy_v2.md SS3. Meant to be invoked by an external
scheduler (cron, a platform's scheduled-task feature, a CI/CD pipeline's
scheduled job runner) on a regular cadence (e.g. daily) — this repository
does not run or manage a scheduler itself (Technical_Architecture_v2.md
SS9 "MVP in-process" precedent: a scheduler is deployment infrastructure,
not application code).

Usage (from backend/, so `app` is importable):
    python scripts/run_retention_cleanup.py
    python scripts/run_retention_cleanup.py --dry-run

Exit code 0 if every expired document was deleted successfully (including
"zero documents were expired" — a normal, common outcome), 1 if any
deletion failed (so a cron wrapper can alert on it) or the process itself
errors before completing.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from app.core.config import get_settings  # noqa: E402
from app.core.logging import configure_logging, get_logger, log_event  # noqa: E402
from app.db.session import create_db_engine, create_session_factory  # noqa: E402
from app.services.retention_service import run_retention_cleanup  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would be deleted without committing (rolls back at the end).",
    )
    args = parser.parse_args()

    settings = get_settings()
    configure_logging(settings.log_level)
    logger = get_logger(__name__)

    engine = create_db_engine(settings)
    session_factory = create_session_factory(engine)
    session = session_factory()

    try:
        summary = run_retention_cleanup(
            session, retention_days=settings.document_retention_days, upload_dir=settings.upload_dir
        )
        if args.dry_run:
            session.rollback()
        else:
            session.commit()
    except Exception:
        session.rollback()
        log_event(
            logger, "retention_cleanup_run_failed", stage="retention", error_category="unexpected_error"
        )
        raise
    finally:
        session.close()

    mode = "DRY RUN -- " if args.dry_run else ""
    print(
        f"{mode}Retention cleanup: cutoff={summary.cutoff.isoformat()} "
        f"candidates={summary.candidates} deleted={summary.deleted} failed={summary.failed}"
    )

    return 1 if summary.failed > 0 else 0


if __name__ == "__main__":
    raise SystemExit(main())
