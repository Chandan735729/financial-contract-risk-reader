# Production Readiness — Phase 11 (Final Operational/Release-Readiness Phase)

**As of:** this phase's work, building on `28f017d` (Phase 10) and all prior phases.
**This document intentionally reports two separate statuses, not one** — see Section 6. A tool that touches real financial documents for a small trusted group of users is a very different bar than one open to unrestricted public traffic, and collapsing those into a single "ready"/"not ready" verdict would misrepresent both.

---

## 1. Functional

| Capability | Status |
|---|---|
| Upload (PDF/DOCX) | Working — content-sniffed validation, size/page/paragraph caps, atomic storage write, per-IP rate limiting |
| Processing pipeline | Working — parsing → segmentation → clause understanding → risk scoring → grounded generation → grounding verification, all wired end-to-end |
| Report | Working — `GET /v1/documents/{id}/report`, four-state (HIGH/MEDIUM/LOW/UNKNOWN) summary + per-clause detail |
| Evidence | Working — verified evidence spans + financial entities, both in the report and the dedicated drill-down endpoint |
| Explanations | Working — grounded plain-language explanations with a safe, spec-exact fallback sentence when grounding fails |
| Document deletion (user-initiated) | Working — `DELETE /v1/documents/{id}`, full cascade, corpus data structurally unreachable through it |
| Document retention (automatic) | Working (new this phase) — `backend/scripts/run_retention_cleanup.py` deletes documents past `document_retention_days` (default 90); **requires an operator to schedule it externally** (cron/platform scheduler) — this repository does not run its own scheduler |
| Health checks | Working (new this phase) — liveness (`GET /health`) and readiness (`GET /health/ready`, checks DB + vector store) are now separate endpoints |
| Operational metrics | Working (new this phase) — `GET /metrics`, safe in-process aggregates only (uploads, job outcomes, durations, generation/grounding failures, fallback rate, rate-limit events, retention events) |
| Frontend | Working — upload, live processing status, full report UI, all four risk states, confidence display, evidence highlighting, filters, accessible disclosure pattern |

## 2. Quality

- **Test suite:** 708 backend tests, 77 frontend tests — all passing as of this phase.
- **Evaluation results (synthetic benchmark, not production accuracy):** DEV macro F1 = 1.00, **TEST macro F1 = 0.54** (unchanged this phase — the Risk Engine itself was out of scope), evidence precision = 1.00 with zero fabrication leaks, `unsupported_factual_claim_rate` = 0.00%, `unsupported_claim_leak_count` = 0 (hard gate). Full report: `corpus/eval/results/`.
- **Known limitations (explicit, not buried):**
  - **The real-world corpus is not yet equivalent to production coverage.** `corpus/build/seed_patterns.py`'s hand-authored `synthetic_seed` patterns are dev-only, clearly tagged as such in the schema, and were never claimed to be a production-representative reference corpus. Real sourcing (a CUAD subset licensing review, permissioned scraping of Indian loan/insurance T&Cs) remains unstarted — **still the single largest gap between this system and a public-launch-quality tool.**
  - **TEST macro F1 remains ~0.54.** A small-sample (12-case), hand-built synthetic benchmark — not a statistically meaningful production-accuracy claim.
  - **Two grounding edge cases remain** (conditionality changes, affected-party changes — `docs/SECURITY_AUDIT.md` SS6). A third, basis-substitution, was found in Phase 10 and **closed in Phase 11** (`docs/PROVISIONAL_DECISIONS.md` P11.6) — a claim can no longer reattach a correctly-cited number to a fabricated basis phrase without being caught, with a narrower residual limitation (very short/generic basis phrases) documented honestly rather than claimed fixed. None of the three (past or present) allow an ungrounded risk verdict, confidence, category, or evidence span to reach a user — all affect explanation prose only.
  - **Jurisdiction-specific legality is not supported and never will be by design** — the language policy hard-bans "illegal"/"invalid"/"unenforceable"/"you must" and any legal conclusion, enforced in the system prompt, UI copy, and the grounding guard's language checks.
  - **This is an informational tool, not legal advice** — stated in the report page's disclaimer and in this document; it does not replace review by a qualified professional.

## 3. Security

Full detail in `docs/SECURITY_AUDIT.md`. Summary:

| Area | Status |
|---|---|
| Framework/dependency security | **Upgraded this phase**: `fastapi==0.133.0`/`starlette==1.6.0` — all 7 previously-flagged starlette advisories closed per `pip-audit`, including the one that was reachable (PYSEC-2026-249; the narrow content-type-gate mitigation from Phase 10 is kept anyway as harmless defense-in-depth). Two accepted-risk findings remain, both not reachable by the deployed application: the pre-existing chromadb advisory (never run in server mode) and a newly-found pytest advisory (dev/test-only dependency, `docs/SECURITY_AUDIT.md` SS4). |
| Token security | 384-bit CSPRNG tokens, `Authorization: Bearer` only (never a URL), never logged |
| Authorization | Server-enforced on every document-scoped route via one shared dependency; full test matrix |
| File handling | Content-sniffed, size/page/paragraph caps, path-traversal-safe storage, atomic writes |
| Prompt injection | Structural FACTS/CONTEXT separation, backstopped by claim-vs-Risk-Engine-facts verification |
| Grounding | Deterministic verifier, zero live-LLM calls in tests, 0.00% unsupported-factual-claim rate; two documented known limitations remain (down from three — basis-substitution closed this phase) |
| Logging / error monitoring | Allowlist-enforced at a single choke point; re-reviewed this phase specifically for exception-message/traceback leakage — no gap found (`docs/SECURITY_AUDIT.md` SS13) |
| Secrets | Full git-history scan clean; `.gitignore` covers the relevant patterns |
| Rate limiting | In-process, per-IP, fixed-window on uploads; **proxy-aware this phase** — `X-Forwarded-For` is now safely resolvable behind exactly one trusted reverse proxy, opt-in via `TRUST_PROXY_HEADERS`, never trusted by default (`docs/PROVISIONAL_DECISIONS.md` P11.5) |
| Configuration | **A real gap found and closed this phase**: `.env.example` documented `CORS_ORIGINS` but the underlying field had no alias, so it was silently ignored — fixed, and a regression test now keeps `.env.example` structurally in sync with `Settings` going forward (`docs/PROVISIONAL_DECISIONS.md` P11.7) |
| Dependencies | `npm audit`: 0 vulnerabilities. `pip-audit`: 2 accepted-risk findings remain (chromadb, pytest), both not reachable by the deployed application |

## 4. Operations

| Area | Status |
|---|---|
| Health | **Split this phase**: `GET /health` (liveness, unchanged) and `GET /health/ready` (new — checks DB + vector store, returns 503 if either is unreachable, no internal detail exposed) |
| Monitoring | **New this phase**: `GET /metrics` — safe in-process aggregate counters/durations (uploads, pipeline job outcomes and durations, generation/grounding failures, fallback rate, rate-limit rejections, retention events). Still no external metrics backend, tracing, or alerting integration — this is a scrape/poll target, not a push-based alerting system; an operator must connect it to one |
| Storage | Local filesystem (`upload_dir`) for originals, local Chroma persistence for the corpus — both still single-instance-only; a multi-instance deployment needs shared storage, which this MVP does not have |
| Retention | **Automatic retention now exists** (`backend/scripts/run_retention_cleanup.py`, idempotent/retry-safe/partial-failure-isolated/observable) alongside user-initiated deletion — but it is not self-scheduling; an operator must wire it into external cron/a platform's scheduled-task feature (`docs/DEPLOYMENT_CHECKLIST.md`) |
| Backups | **Documented and partially verified this phase** (`docs/BACKUP_AND_RESTORE.md`): delegates to the managed PostgreSQL provider's automated backups as the primary mechanism, with a documented `pg_dump`/`pg_restore` fallback. A real backup/restore smoke test exists and passes for the SQLite mechanism (file-copy backup/restore, exercised end-to-end in this repo); the PostgreSQL path is documented but **not exercised in this development sandbox** (no `pg_dump`/`pg_restore` client tools installed, no live Postgres instance available) — an operator must verify it against a real/staging instance before relying on it. |
| Rate limits | Upload endpoint only, in-process, per-worker-process state; now proxy-aware (see Security table) |
| Concurrency | Explicitly single-worker MVP — the background analysis pipeline, the rate limiter, the metrics registry, and local storage all assume this; do not scale to multiple workers/instances without revisiting all four |
| Deployment procedure | **Documented this phase**: `docs/DEPLOYMENT_CHECKLIST.md` — pre-deploy/deploy/post-deploy/rollback. No Dockerfile/Procfile/platform-specific config exists in this repository yet; the checklist is platform-agnostic by necessity. |

## 5. Known Limitations (explicit summary)

- Real-world corpus coverage is not yet equivalent to production coverage — the current corpus is a small, clearly-tagged synthetic seed set. **Unchanged this phase — still the largest gap to public-launch quality.**
- TEST macro F1 remains ~0.54 on a small synthetic benchmark — not a production-accuracy claim. **Unchanged this phase.**
- Two grounding edge cases remain in the explanation layer only (never the risk verdict) — down from three; basis-substitution was closed this phase.
- Jurisdiction-specific legality is not supported by design.
- This is an informational tool, not legal advice, and should not be the sole basis for a financial or legal decision.
- Single-instance/single-worker architecture throughout (storage, rate limiter, metrics, background pipeline) — a deliberate, documented MVP boundary, not an oversight.
- The PostgreSQL backup/restore procedure is documented but not exercised end-to-end in this repository's own environment (no live instance available) — an operator must verify it once before trusting it.

## 6. Status — reported separately, not collapsed into one verdict

### TRUSTED PILOT READY: **Yes**

Suitable for a small, trusted, invite-only pilot deployment — internal use, or a limited beta where users understand it is an early-stage tool and where the operator actively monitors it. This status is warranted because, as of this phase:

- Every previously-identified operational gap that blocks *safe, monitorable* operation at small scale is closed: automatic retention exists, health/readiness are properly split for an orchestrator to use, safe operational metrics exist, the rate limiter is proxy-aware, backups are documented (and partially verified), a deployment/rollback procedure is written down, and the framework-level dependency risk accepted in Phase 10 is now closed.
- A real, previously-undetected production-configuration bug (`CORS_ORIGINS` silently ignored) was found and fixed *before* it could affect a real deployment, with a regression test guarding against recurrence — evidence this phase's review was substantive, not a formality.
- The one grounding gap Phase 10 flagged as its most concerning open item (basis-substitution) was found to be genuinely fixable without the false-positive risk that sank two earlier attempts at hardening this same code, and was fixed with a verified zero-regression track record.
- Security posture, authorization, and the fail-closed safety properties of the Risk Engine and Grounding Guard are unchanged from Phase 10's audited state, now with one fewer known gap.

**Operating conditions for a trusted pilot:** an operator must schedule the retention cleanup script externally, set real production configuration (`docs/DEPLOYMENT_CHECKLIST.md`), confirm the managed database provider's automated backups are enabled, and actively watch `GET /metrics` and application logs — this system does not yet page anyone on its own.

### PUBLIC LAUNCH READY: **No**

Not recommended for open, unrestricted public launch. This is not a security or operational judgment — the gaps above are closed or manageable at pilot scale — it is an accuracy and scale judgment:

1. **The evaluation corpus is synthetic, not real-world.** No amount of operational hardening changes the fact that risk classification has only ever been measured against a small, hand-built benchmark. Real-world accuracy is genuinely unknown.
2. **TEST macro F1 (~0.54) is not a production-accuracy number**, and it was explicitly out of scope for this phase to change (the Risk Engine itself was excluded from this phase's remit).
3. **Single-instance architecture throughout** (storage, rate limiter, metrics, background pipeline) has no path to horizontal scaling without dedicated work — untenable for unrestricted public volume.
4. **No external monitoring/alerting integration exists** — `GET /metrics` is a scrape target, not a paging system; at public scale, silent failure becomes a real risk without someone actively watching.
5. **Two grounding edge cases remain**, and the fix shipped this phase carries an honestly-documented residual limitation of its own — acceptable risk for a small, informed pilot audience; not yet validated at the scale and adversarial diversity a public launch would face.

None of the above are absent from this document by oversight — they are the explicit, prioritized punch list for whatever phase eventually targets public launch, should that be pursued.
