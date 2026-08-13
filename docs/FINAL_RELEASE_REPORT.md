# Final Release Report — Phase 11 (Operational Readiness & Final Release Gate)

**This is the final phase of planned work on this codebase.** This report
is the closing record of what this system is, what it does and does not
do, what was verified before this point, and what remains open. It is
written to be read on its own, without needing the rest of this repo's
phase history as context.

---

## 1. Executive Summary

The Financial Contract Risk Reader is a tool that ingests a loan or
insurance contract (PDF/DOCX), segments it into clauses, classifies each
clause's risk level (HIGH/MEDIUM/LOW/UNKNOWN) against a deterministic Risk
Engine and a labeled corpus, and generates a grounded, plain-language
explanation for higher-risk clauses — verified by a Grounding Guard before
ever being shown to a user. Eleven phases of work built this from an empty
repository to a system with a working end-to-end pipeline, a frontend
report UI, a security-hardening pass, and — this phase — the operational
infrastructure (retention, health checks, metrics, backups, deployment
procedure) and a final dependency/configuration/grounding review needed
for a controlled trusted-pilot deployment.

**Status, in one line: ready for a small, trusted, monitored pilot. Not
ready for open public launch.** Section 15 explains why these are
reported as two separate statuses, not one.

## 2. Scope of This Phase (Phase 11)

Explicitly in scope: framework/dependency security (the FastAPI/Starlette
upgrade Phase 10 deferred), automatic data retention, operational
readiness (health/readiness split, safe metrics), a grounding hardening
attempt on the one security-relevant limitation Phase 10 left unfixed
(basis-substitution), production configuration review, deployment
documentation, and this final release gate. Explicitly out of scope (per
this phase's own instructions, honored throughout): no chat, document
comparison, mobile app, multi-language support, negotiation/redlining
tooling, new risk categories, or any other product redesign. The Risk
Engine's classification logic and taxonomy were not touched.

## 3. What This Application Does

- Accepts a PDF or DOCX loan/insurance contract upload, validated by
  content-sniffing (never trusting file extension or declared MIME type).
- Segments the document into clauses and classifies each one's risk level
  using a deterministic, rule-based Risk Engine plus a labeled reference
  corpus (retrieval-augmented, not an LLM classification).
- For HIGH/MEDIUM clauses, generates a plain-language explanation via an
  LLM (Anthropic), which is then mechanically verified against the
  clause's own evidence before it is ever shown — an unsupported claim is
  replaced with a safe, fixed fallback sentence, never displayed as-is.
- Surfaces evidence spans and extracted financial entities (amounts,
  percentages, dates) supporting each classification.
- Lets the access-token holder delete their document and all derived data
  on request, and automatically deletes documents past a configurable
  retention window (default 90 days).

## 4. What This Application Does NOT Do (explicit non-goals)

- It does not provide legal advice, and its language policy structurally
  forbids the words "illegal," "invalid," "unenforceable," "you must," or
  any other legal conclusion, in both the system prompt and the Grounding
  Guard's verification checks.
- It does not assess jurisdiction-specific enforceability, by design —
  this is a permanent scope boundary, not a gap to be closed later.
  Never claims accuracy for real-world production use — see Section 7.
- It does not support chat, negotiation, document comparison, or any
  interactive back-and-forth with the model about a document.
- It does not run on more than one worker process or more than one
  instance — this is an explicit, documented MVP architectural boundary
  (Technical_Architecture_v2.md SS9), not an oversight.

## 5. Architecture Overview

FastAPI backend + PostgreSQL (production) / SQLite (dev-only) + a local
Chroma vector store holding only the permanent labeled corpus (never
per-user document data) + Next.js frontend. Background processing runs
in-process via FastAPI `BackgroundTasks` (no Celery/Redis). Full detail:
`docs/Technical_Architecture_Financial_Contract_Risk_Reader_v2.md`.

## 6. Functional Capability Summary

See `docs/PRODUCTION_READINESS.md` Section 1 for the full capability
table. Every capability listed there is implemented and covered by
automated tests; none are aspirational or partially stubbed.

## 7. Accuracy & Evaluation Summary — NOT a production-accuracy claim

**This section makes no claim that this system is accurate enough for
unsupervised real-world use.** All numbers below come from a small,
hand-built synthetic benchmark (`corpus/eval/`), not real contracts:

- DEV macro F1 = 1.00, **TEST (held-out) macro F1 = 0.54** — a 12-case
  benchmark; not statistically meaningful as a production-accuracy number.
  Unchanged this phase (the Risk Engine was out of scope).
- Evidence precision = 1.00, zero fabrication leaks.
- `unsupported_factual_claim_rate` = 0.00% on this benchmark — the
  safety-relevant grounding metric — with `unsupported_claim_leak_count`
  = 0 as a hard gate in the evaluation pipeline.
- The reference corpus itself (`corpus/build/seed_patterns.py`) is a
  small, explicitly-tagged (`source="synthetic_seed"`) synthetic set, not
  a real-world reference corpus. Real sourcing remains unstarted future
  work and is, by a wide margin, the largest gap between this system and
  one that could make a credible real-world accuracy claim.

## 8. Security Summary

Full detail: `docs/SECURITY_AUDIT.md`. This phase: upgraded
`fastapi`/`starlette` (closing all 7 previously-flagged starlette
advisories), made the upload rate limiter safely proxy-aware (opt-in,
never trusting `X-Forwarded-For` by default), found and fixed a real
production-configuration bug (`CORS_ORIGINS` was silently ignored — see
`docs/PROVISIONAL_DECISIONS.md` P11.7), and re-reviewed error-monitoring
payload safety (no gap found). Two dependency findings remain as
documented accepted risk, neither reachable by the deployed application:
chromadb (server-mode-only vulnerability, this app never runs chromadb in
server mode) and pytest (dev/test-only dependency, found this phase).

**This report does not constitute a security certification.** No
external penetration test, red-team exercise, or third-party security
audit has been performed at any point in this project's history — see
`docs/SECURITY_AUDIT.md` Section 10 for the full, explicit list of what
the internal audits did not cover.

## 9. Grounding & Explanation Safety Summary

The Grounding Guard mechanically verifies every claim in a generated
explanation against the clause's own evidence before display — never
trusting the LLM's self-report. As of this phase: **two** known
limitations remain (conditionality changes, affected-party changes), down
from three — a third (basis-substitution: a claim reattaching a real
number to a fabricated basis, e.g. "2% of the outstanding principal"
reworded as "2% of the borrower's monthly loan payment") was found by
Phase 10 and **closed this phase** with a narrow, additive, proximity-
windowed check, verified against 11 new adversarial tests across 8
categories and a full regression run showing zero change to any existing
metric. Full detail: `docs/EXPLANATION_GROUNDING_NOTES.md` Section 8,
`docs/PROVISIONAL_DECISIONS.md` P11.6. **None of the remaining
limitations, past or present, ever allow an ungrounded risk verdict,
confidence score, category, or evidence span to reach a user** — they
affect explanation prose only, and are all tested and documented, not
hidden.

## 10. Operational Readiness Summary

New this phase: liveness/readiness split (`GET /health`, `GET
/health/ready`), safe in-process operational metrics (`GET /metrics`),
automatic document retention (`backend/scripts/run_retention_cleanup.py`,
requires external scheduling), and documented backup/restore procedures
(`docs/BACKUP_AND_RESTORE.md` — the SQLite mechanism is verified
end-to-end by a real smoke test in this repo; the PostgreSQL mechanism is
documented but not exercised in this development sandbox, since no
`pg_dump`/`pg_restore` tools or live instance are available here). A full
deployment procedure is written down (`docs/DEPLOYMENT_CHECKLIST.md`),
though no Dockerfile/Procfile/platform-specific config exists in this
repository yet. Full detail: `docs/PRODUCTION_READINESS.md` Section 4.

## 11. Dependency & Configuration Summary

`backend/.env.example` is now complete and structurally verified to stay
in sync with `Settings` (`backend/tests/test_config.py::test_env_example_stays_in_sync_with_every_settings_field`)
— a real drift (the `CORS_ORIGINS` gap, Section 8) was found and fixed
this phase specifically because this review was performed, not assumed
clean. `pip-audit`/`npm audit` results: Section 8.

## 12. Known Limitations (consolidated)

- Synthetic, not real-world, evaluation corpus and TEST accuracy (Section 7) — the largest open gap.
- Two grounding edge cases remain in explanation prose only (Section 9).
- A residual limitation in this phase's own basis-substitution fix: very short/generic basis phrases can still slip past (`docs/PROVISIONAL_DECISIONS.md` P11.6).
- Single-instance/single-worker architecture throughout (storage, rate limiter, metrics registry, background pipeline) — deliberate MVP boundary, not a bug.
- The PostgreSQL backup/restore path is documented but not exercised end-to-end in this environment.
- No external monitoring/alerting/paging integration — `GET /metrics` is a scrape target an operator must connect to something.
- Jurisdiction-specific legality is unsupported by design, permanently.
- No Dockerfile/Procfile/platform-specific deployment config exists in-repo yet.

## 13. Final Code Audit Results

A repository-wide grep for TODO/FIXME/debug artifacts, `print()`/
`console.log`, hardcoded credentials, secret-shaped strings, unsafe shell
invocation, unsafe HTML injection, tokens-in-URLs, and raw-content logging
found **no unaddressed issues**. Every match was individually classified:
`print()` calls exist only in standalone CLI scripts (`backend/scripts/`)
as intended operator-facing output, never in application/request-handling
code; the one `subprocess.run` call (`test_migration.py`) uses a fixed
argument list against the trusted local `alembic` CLI, never `shell=True`;
API-key-shaped strings only appear in `test_config.py` as deliberately
fake values used to test that real secrets never leak; access tokens are
never placed in a URL anywhere in the backend or frontend (confirmed by
grep, matching the Phase 8 architectural decision); zero direct
`logger.*()` calls exist anywhere in `backend/app` (everything funnels
through the allowlisted `log_event`, re-confirmed by grep this phase); no
`dangerouslySetInnerHTML`/raw `innerHTML` writes exist in the frontend; no
`.env`/credential files are tracked in git.

## 14. Final Test & Evaluation Results

- Backend: **708 tests passed**, 0 failed.
- Frontend: **77 tests passed**, 0 failed.
- `ruff check`, `ruff format --check`, `mypy` (backend): clean.
- `eslint`, `tsc --noEmit` (frontend): clean.
- `python corpus/eval/run_all.py`: **REGRESSION GATE: PASSED.** DEV macro F1 = 1.00, TEST macro F1 = 0.54 (unchanged, not modified this phase), evidence precision = 1.00, zero fabrication leaks, `unsupported_factual_claim_rate` = 0.00%, `unsupported_claim_leak_count` = 0, adversarial cases 9 pass / 0 fail / 0 known_gap / 1 observe.
- `pip-audit`: 2 accepted-risk findings (Section 8), neither reachable. `npm audit`: 0 vulnerabilities.
- `git diff --check`: no whitespace errors. Secret-pattern scan of the full diff and all new files: no matches.

## 15. Release Status

See `docs/PRODUCTION_READINESS.md` Section 6 for the full reasoning.
Reported as two separate statuses, deliberately not collapsed into one:

- **TRUSTED PILOT READY: Yes** — for a small, invite-only, actively-monitored deployment where the operator schedules retention cleanup externally, sets real production configuration, and watches `GET /metrics`/logs.
- **PUBLIC LAUNCH READY: No** — blocked on real-world evaluation corpus and accuracy validation, horizontal-scaling work, and external monitoring/alerting integration (Section 12), none of which were in scope for this phase.

## 16. Final Disclaimers

**This is not legal advice.** Nothing in this system's output, this
report, or any other document in this repository should be relied upon
as a substitute for review by a qualified legal or financial professional.

**This report makes no production-accuracy claim.** Every evaluation
number in this document comes from a small, synthetic, hand-built
benchmark. Real-world classification accuracy on actual contracts is
genuinely unknown and has never been measured.

**This report does not constitute a security certification.** The
security work described here (Section 8, `docs/SECURITY_AUDIT.md`) is
internal, code-level review — deterministic testing, dependency
scanning, and adversarial test cases — not an independent third-party
audit, penetration test, or compliance certification of any kind.

This is the final phase of planned work on this codebase per the scope
given for this project. No further feature phase follows this report.
