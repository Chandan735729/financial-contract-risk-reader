# Deployment Checklist — Phase 11

This is an operational checklist for a controlled, trusted-pilot deployment
(see `docs/PRODUCTION_READINESS.md` for the accuracy/security status this
checklist assumes). It targets the deployment shape this project has
documented since v1 (Technical_Architecture_v2.md SS9): Next.js frontend
on a managed platform (e.g. Vercel), FastAPI backend + PostgreSQL on a
managed platform (e.g. Railway/Render), Chroma co-located with the
backend or as a managed instance. **No Dockerfile, Procfile, or
platform-specific config file exists in this repository yet** — this
checklist is deliberately platform-agnostic rather than inventing
infrastructure config that hasn't been decided; an operator adapts the
commands below to their chosen platform's deploy mechanism.

This is **not** a claim that this checklist has been executed against a
real production environment — no such environment exists as of this
phase. It is the operational procedure derived from what this codebase
actually requires to run correctly, cross-referenced against every
relevant doc (`docs/SECURITY_AUDIT.md`, `docs/BACKUP_AND_RESTORE.md`,
`docs/PROVISIONAL_DECISIONS.md`).

---

## 1. Pre-Deploy

**Configuration** (`backend/.env.example` is the authoritative list —
kept in sync with `Settings` by `backend/tests/test_config.py::test_env_example_stays_in_sync_with_every_settings_field`):

- [ ] `ENVIRONMENT=production` — this makes `Settings._validate_production_requirements` enforce the next two items at startup (fails fast, not at first use).
- [ ] `DATABASE_URL` set to a real PostgreSQL connection string (not sqlite). Confirm the managed provider's automated backups are enabled on the chosen plan (`docs/BACKUP_AND_RESTORE.md` SS1) — some providers gate this behind a paid tier.
- [ ] `ANTHROPIC_API_KEY` set to a real key, provisioned via the hosting platform's secret manager — never committed, never in a plain `.env` on disk in a shared environment.
- [ ] `CORS_ORIGINS` set to the real frontend origin(s) — **never** left at the `http://localhost:3000` development default (this was a real, silently-broken gap until Phase 11 — see `docs/PROVISIONAL_DECISIONS.md` P11.7 — confirm it actually takes effect, don't just set it and assume).
- [ ] `TRUST_PROXY_HEADERS` set to `true` **only if** this deployment genuinely sits directly behind exactly one trusted reverse proxy that sets `X-Forwarded-For` itself (the platform's own routing layer). Leave `false` otherwise — see `docs/PROVISIONAL_DECISIONS.md` P11.5.
- [ ] `UPLOAD_DIR` and `CHROMA_PERSIST_DIR` point at persistent, writable storage that survives a redeploy/restart (a managed platform's ephemeral filesystem does **not** — confirm a persistent volume or equivalent is attached; this is a known single-instance-storage limitation, `docs/PRODUCTION_READINESS.md` SS4).
- [ ] `DOCUMENT_RETENTION_DAYS` reviewed (default 90, `Security_and_Privacy_v2.md` SS3's example window).
- [ ] Frontend `NEXT_PUBLIC_API_BASE_URL` points at the real deployed backend URL (not `localhost`).
- [ ] No `.env`/`.env.local` file is committed anywhere in the deployed artifact (confirm `.gitignore` coverage, same check every prior phase's git-safety review already performed).

**Database:**

- [ ] Run outstanding Alembic migrations against the target database **before** starting the new backend version: `cd backend && alembic upgrade head`. Confirm the migration completes cleanly against a copy/staging instance first if this deploy includes a schema change.
- [ ] If this is a first-ever deploy to a fresh database, confirm `alembic upgrade head` alone brings the schema to the current version (no reliance on `Base.metadata.create_all` in production — that path exists for the test suite and local dev only).

**Corpus:**

- [ ] Confirm the corpus is built for the running `taxonomy_version`/`corpus_version` pair (`Settings.taxonomy_version`/`Settings.corpus_version`) in the target `CHROMA_PERSIST_DIR`: from `backend/`, run `python ../corpus/build/build_corpus.py`. Idempotent — safe to re-run.

**Verification, before touching anything live:**

- [ ] Full backend test suite green: `cd backend && python -m pytest`.
- [ ] `ruff check .`, `ruff format --check .`, `mypy .` all clean (`backend/`).
- [ ] Frontend test suite green: `cd frontend && npm test`.
- [ ] Frontend `npm run lint` / `npm run typecheck` clean.
- [ ] `python corpus/eval/run_all.py` regression gate passes (hard gates: DEV macro F1 floor, zero fabrication leaks, 100% HIGH/MEDIUM evidence coverage, zero unsupported-claim leaks) — see current numbers in `docs/PRODUCTION_READINESS.md`.
- [ ] `pip-audit` (backend) and `npm audit` (frontend) reviewed — no new, unaccepted findings since the last run recorded in `docs/SECURITY_AUDIT.md`.
- [ ] Backup/restore smoke test run at least once against a real (e.g. staging) PostgreSQL instance if this is the first deploy to a new database provider — `docs/BACKUP_AND_RESTORE.md` SS4 (the SQLite half is verified by CI-equivalent test runs already; the PostgreSQL half is not, by design, since no live instance exists in the dev sandbox).

---

## 2. Deploy

1. Deploy the backend first (frontend depends on it being reachable; the reverse order risks a frontend serving against a stale/unreachable API).
   - Start command: `uvicorn app.main:app --host 0.0.0.0 --port $PORT` (from `backend/`, with the venv/deployed dependencies from `requirements.txt` installed).
2. Once the backend is up, confirm liveness and readiness **before** deploying the frontend or routing real traffic to it:
   - `GET /health` → `200 {"status": "ok", ...}`.
   - `GET /health/ready` → `200 {"ready": true, "checks": {"database": {"ok": true}, "vector_store": {"ok": true}}}`. A `503` here means do not proceed — see Rollback below.
3. Deploy the frontend (`npm run build && npm run start`, or the platform's equivalent for Next.js).
4. End-to-end smoke test against the live deployment (not a local/test environment): upload a small synthetic PDF or DOCX through the real frontend (or directly via `POST /v1/documents`), poll `GET /v1/documents/{id}/status` until `completed`, fetch `GET /v1/documents/{id}/report`, and confirm the report renders with at least one clause. This exercises the full pipeline (parsing → segmentation → understanding → scoring → generation → grounding) against the real deployed configuration, not a mocked one.
5. Confirm `GET /metrics` is reachable and `counters.documents_uploaded` reflects the smoke-test upload.

---

## 3. Post-Deploy

- [ ] Watch `GET /metrics` for the first hour of real (or pilot-user) traffic: `pipeline_jobs_completed` vs `pipeline_jobs_failed`, `explanations_generation_failed`, `explanations_fallback_used`, `upload_rate_limit_rejections` (an unexpectedly high count may mean `upload_rate_limit_max_requests` is too low for real usage, or `trust_proxy_headers` is misconfigured and legitimate users are sharing one bucket).
- [ ] Confirm structured logs (stdout JSON via `app/core/logging.py`) are actually reaching wherever this deployment's platform aggregates them — this is the only error-monitoring mechanism this repository has (`docs/SECURITY_AUDIT.md` SS13); if logs aren't being captured, failures are invisible.
- [ ] Schedule `backend/scripts/run_retention_cleanup.py` on the hosting platform's cron/scheduled-task feature (daily is a reasonable cadence for a 90-day window) — this repository does not run its own scheduler, so this step is not optional infrastructure, it is a required manual action. Confirm the first scheduled run actually executes and exits 0 (`--dry-run` first is recommended for the very first run against a real database).
- [ ] Confirm the reverse proxy / platform routing is actually the single trusted hop `TRUST_PROXY_HEADERS`/`resolve_client_ip` assumes, if that setting is `true` — a misconfigured multi-hop setup (e.g. a CDN in front of the platform's own proxy) would make the "trust the rightmost entry" assumption resolve to the wrong IP (`docs/PROVISIONAL_DECISIONS.md` P11.5).

---

## 4. Rollback

**If `GET /health/ready` returns `503` after deploying the new backend version** (before any real traffic is routed to it): do not proceed to frontend deploy or traffic cutover. Check which dependency failed (`checks.database.ok` / `checks.vector_store.ok` — the response never includes *why*, by design, so check the platform's own connectivity to Postgres/the Chroma persistence path directly). Roll back to the previous known-good backend deployment/image on the hosting platform.

**If a database migration was part of this deploy and needs to be undone:** `cd backend && alembic downgrade -1` against the target database, then redeploy the previous backend version. Confirm the previous backend version is compatible with the downgraded schema before doing this — Alembic tracks schema state, not application-code compatibility.

**If the new version is live and serving traffic but is producing bad results** (elevated `pipeline_jobs_failed`/`explanations_generation_failed` in `GET /metrics`, or a user-reported issue): redeploy the previous known-good backend/frontend versions via the hosting platform's normal rollback mechanism (e.g. redeploying a prior build/image). No database rollback is implied by an application-code-only regression — only roll back the schema (previous paragraph) if the bad deploy specifically included a migration.

**Data loss scenario** (the database itself is corrupted or lost, not just a bad code deploy): restore from the managed provider's automated backup, or from a manual `pg_dump` export if one was taken — full procedure in `docs/BACKUP_AND_RESTORE.md` SS1. Uploaded-file storage restoration (if using local-disk storage) is SS2 of the same document. The Chroma corpus never needs restoring from backup — rebuild it directly from source (from `backend/`): `python ../corpus/build/build_corpus.py`.

**This is not legal advice and this checklist does not constitute a security certification** — see `docs/FINAL_RELEASE_REPORT.md` and `docs/PRODUCTION_READINESS.md` for the full, honest status of what this application does and does not guarantee.
