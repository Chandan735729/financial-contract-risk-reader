# Backup and Restore — Phase 11

**Scope:** the two stateful stores a deployment of this application owns —
the PostgreSQL database (system of record) and the local `upload_dir`
(original uploaded files). Corpus/vector-store data is deliberately excluded
— see SS3 below, it does not need backing up at all.

This document follows the same discipline as the rest of Phase 11: it
describes exactly what has been verified to work in this repository, and is
explicit about what has not.

## 1. Database (PostgreSQL)

**Primary strategy: delegate to the managed hosting provider.**
Technical_Architecture_v2.md SS9 already specifies the production database
runs on a managed provider (Railway/Render). Every mainstream managed
Postgres offering includes automated daily backups (and, on most paid
tiers, point-in-time recovery) as a feature of the service itself. Standing
up separate backup infrastructure for a single-instance MVP database would
be exactly the kind of "enterprise backup infra" this phase was told not to
build when the hosting provider already provides it. **Operator action
required at deploy time:** confirm the chosen plan has automated backups
enabled (some providers gate this behind a paid tier) and note the
provider's stated retention window and restore procedure — both vary by
provider and are outside this repository's control.

**Portable fallback / manual export:** `pg_dump`/`pg_restore` work against
any PostgreSQL instance regardless of hosting provider, and are the
mechanism to use for an ad hoc export (e.g. before a risky migration) or if
migrating between providers:

```bash
# Backup (custom format — compressed, supports selective/parallel restore)
pg_dump --format=custom --file=backup_$(date +%Y%m%d_%H%M%S).dump "$DATABASE_URL"

# Restore into a fresh, empty database
createdb contract_risk_reader_restored
pg_restore --clean --if-exists --dbname=contract_risk_reader_restored backup_20260101_020000.dump
```

`DATABASE_URL` is the same connection string the application reads from
`Settings.database_url` (`backend/app/core/config.py`) — never commit it,
never log it (the existing `safe_summary()` convention already enforces
this for application logs).

**Restore verification:** after any real restore, confirm application
health via `GET /health/ready` (SS added in this phase, see
`docs/DEPLOYMENT_CHECKLIST.md`) and spot-check that a known document/report
is queryable, before pointing production traffic at the restored database.

## 2. Uploaded document storage (`upload_dir`)

Local filesystem storage is a known, already-documented single-instance
limitation (`docs/PRODUCTION_READINESS.md` SS4 Operations table) — it has
no redundancy of its own. For a trusted-pilot deployment (small volume,
single instance), the pragmatic backup approach is a periodic archive of the
directory, scheduled the same way the retention cleanup job is (external
cron / platform scheduled task — see `backend/scripts/run_retention_cleanup.py`
for the precedent):

```bash
tar -czf uploads_backup_$(date +%Y%m%d).tar.gz -C /path/to upload_dir
```

Restore is the inverse: extract the archive back into the configured
`upload_dir` path. Because the retention cleanup job (Phase 11) already
deletes documents past `document_retention_days`, an uploads backup taken
before a document's retention cutoff is only useful for the restore window
before that document would have been purged anyway — backup retention
should not be configured to outlive `document_retention_days` for no
reason.

**Known limitation, not solved this phase:** true redundancy for uploaded
files requires object storage (S3-compatible), already flagged as future
work in `docs/PRODUCTION_READINESS.md`. A single-instance local-disk
deployment's uploads are only as durable as that instance's disk — a
periodic archive (above) is a mitigation, not a fix.

## 3. Vector store / corpus data — deliberately excluded

The Chroma persistence directory (`chroma_persist_dir`) holds only the
permanent, non-user-specific labeled corpus (Technical_Architecture_v2.md
SS6) — no per-user document embeddings persist there. It is fully
regenerable at any time from source: `corpus/build/seed_patterns.py` +
`corpus/build/build_corpus.py` (idempotent, already used to build it in
the first place — run from `backend/` as `python ../corpus/build/build_corpus.py`).
It never needs a backup/restore procedure of its own; if lost, re-run the
build script.

## 4. Smoke test — proving the procedure actually works

`backend/scripts/backup_restore_smoke_test.py` is not documentation-only —
it actually performs a backup/restore cycle against a real (temporary)
database and verifies a specific row survives it, rather than merely
asserting the commands look right on paper.

```bash
cd backend
.venv/Scripts/python.exe scripts/backup_restore_smoke_test.py --sqlite-only
```

**SQLite path — verified, passes in this repository today.** It builds a
throwaway SQLite database, writes a marker document, backs it up via a
plain file copy (the correct, documented way to snapshot a SQLite database
that isn't being concurrently written to —
https://www.sqlite.org/backup.html — true here both because the smoke test
itself is offline/quiesced and because this application's own deployment is
always single-worker, Technical_Architecture_v2.md SS9), deletes the live
file to simulate loss, restores from the backup, and asserts the marker
document comes back with the exact data it was written with. Output ends
with `[sqlite] PASS: marker document survived a real backup/restore cycle.`

**PostgreSQL path — documented, NOT exercised in this environment.** This
development sandbox does not have the `pg_dump`/`pg_restore`/`psql` client
binaries installed (checked during this phase — none are on `PATH`), and
there is no live PostgreSQL instance available to test against here. The
script detects this and reports it plainly (`[postgres] SKIPPED ...`)
rather than claiming a pass it didn't earn. **Before relying on the
PostgreSQL backup/restore procedure in a real deployment, an operator must
run the `pg_dump`/`pg_restore` commands in SS1 by hand against a disposable
staging database at least once** and confirm the restored data is correct
— this repository provides the documented commands and the verified SQLite
half of the mechanism, but does not claim to have verified the Postgres
half end-to-end.

## 5. Summary

| Store | Backup mechanism | Verified in this repo? |
|---|---|---|
| PostgreSQL (production) | Managed provider's automated backups (primary); `pg_dump`/`pg_restore` (portable fallback) | Commands documented; SQLite-equivalent mechanism verified by the smoke test; the Postgres path itself is not exercised in this sandbox (no client tools, no live instance) |
| `upload_dir` (local storage) | Periodic `tar` archive via external scheduler | Mechanism is standard `tar`/extract; not scripted or scheduled by this repository (matches the "no heavyweight infra beyond what's needed" MVP precedent) |
| Chroma corpus data | None needed — regenerate from `corpus/build/` | N/A — rebuild is exercised routinely during development |
