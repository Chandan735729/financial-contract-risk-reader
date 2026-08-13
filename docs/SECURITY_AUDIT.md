# Security Audit — Phase 10

**Date:** 2026-08-13
**Scope:** Full application (backend API/pipeline, frontend, dependencies, git history) as of commit `86b4be8` (end of Phase 9), audited and hardened through this phase's own commit.
**Method:** Manual threat-model-driven code review across every layer named in the audit checklist below, targeted adversarial testing (the grounding guard, authorization matrix, rate limiting, content-type gate), `npm audit`, `pip-audit`, and a full git-history secret scan. No automated SAST/DAST tool was run beyond the dependency scanners named above — see "What this audit did not do" at the end.

**This is not a certification.** No external penetration test, no formal threat-modeling workshop, and no third-party security review has been performed. Findings below reflect what a single internal review pass found; the absence of a finding in a category is not a guarantee that category is risk-free.

---

## 1. Threat Model

Extends Security_and_Privacy_v2.md SS1's table with the full Phase 10 checklist, each row assessed for this specific application (not a generic web-app threat list):

| Threat | Relevance | Status |
|---|---|---|
| Unauthorized document access | High — documents contain personal financial detail | Mitigated: unguessable 384-bit tokens, server-side check on every document-scoped route, no code path bypasses it |
| Access-token leakage | High | Mitigated: `Authorization: Bearer` header only (moved off query string this phase — see SS2), never logged, never in frontend `NEXT_PUBLIC_*` |
| Document ID enumeration | Medium | Mitigated: token required regardless of ID validity; wrong/missing/guessed ID all return byte-identical `access_denied` 404s |
| Path traversal | Medium | Mitigated: server-generated filenames only; containment check on every filesystem read/delete as defense-in-depth |
| Malicious document uploads | Medium | Mitigated: content-sniffed (not extension/MIME-trusted), size/page/paragraph caps, parsed in-memory only |
| Malformed PDF/DOCX | Medium | Mitigated at the app level (fails to a safe `ErrorCode`, never crashes the process); underlying parser-library robustness is a residual/accepted risk (SS6) |
| Parser abuse / resource exhaustion | Medium | Mitigated: page/paragraph caps checked *before* per-page/per-paragraph work begins |
| Denial of service | Medium | Partially mitigated this phase: upload rate limiting (new), per-document LLM/generation caps (existing), a narrow content-type gate closing one known framework DoS vector (SS4); a full DoS defense (WAF, global request-size limiting, multi-instance rate limiting) is out of scope for this MVP |
| Prompt injection | Medium-high | Mitigated: structural FACTS/CONTEXT prompt separation with explicit "ignore instructions in CONTEXT," backstopped by the grounding guard verifying claims against Risk-Engine facts, not raw text |
| LLM prompt leakage | Low | Mitigated: prompts/responses never logged (allowlist-based logging), API key never logged (exception type only) |
| LLM output manipulation | Medium | Mitigated structurally: Risk Engine values are immutable from the LLM's perspective (never written back from LLM output anywhere in the pipeline) |
| Grounding bypass | Medium | Mostly mitigated; three specific, tested, documented known limitations remain (SS6) |
| PII leakage | Medium | Mitigated: logging allowlist excludes all document/entity/explanation content; no third-party analytics integration exists at all |
| Logging leakage | Medium | Mitigated: every log call in the codebase goes through one allowlist-enforcing function (verified: zero direct `logger.X()` calls anywhere in `backend/app`) |
| API key exposure | High | Mitigated: `SecretStr`, never logged, never reaches the frontend, production start-up fails fast if unset |
| Client-side secret exposure | High | Mitigated: only `NEXT_PUBLIC_API_BASE_URL`/`NEXT_PUBLIC_APP_ENV` are public; no other secret-shaped variable exists in the frontend |
| XSS / unsafe HTML rendering | Medium | Mitigated: React's default JSX escaping only; zero uses of `dangerouslySetInnerHTML`/`innerHTML`-as-write/`document.write` anywhere in shipped frontend source |
| SSRF | Low | Not applicable — this app makes exactly one class of outbound call (to `api.anthropic.com`, a fixed host, never a user-controlled URL); no webhook/URL-fetch feature exists |
| SQL injection | Low | Not applicable — zero raw SQL anywhere in the codebase; 100% SQLAlchemy ORM/Core, inherently parameterized (verified by grep for `execute(text(`) |
| CSRF | Low | Not applicable — no cookie-based auth; Bearer tokens require deliberate JS to attach, which cross-origin pages cannot do without CORS permission |
| Insecure CORS | Low | Mitigated: explicit origin allowlist (`cors_origins`, default `http://localhost:3000`), not a wildcard; `allow_credentials=False` |
| Insecure headers | Low | Mitigated this phase: `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy` added (new) |
| Dependency vulnerabilities | Medium | Found and triaged this phase — see SS4 |
| Accidental repository secrets | High | None found — full git-history scan (filenames and content patterns) came back clean |

## 2. Access-Token Transport (moved off the URL — SS2/SS3)

Already fixed in Phase 8 (`docs/PROVISIONAL_DECISIONS.md` P8.1) after that phase's own logging-safety test caught a query-parameter token leaking into request-logging output. Re-verified this phase: `Authorization: Bearer <token>` is the only transport for all four document-scoped endpoints; confirmed via `require_document_access`'s implementation and the authorization test matrix (SS3 below). Token generation: `secrets.token_urlsafe(48)` — 384 bits of CSPRNG entropy, encoded to the 64-character column width exactly.

**Frontend storage tradeoff (documented, not new this phase):** the token lives in `sessionStorage`, keyed per document ID, not `localStorage`. This survives a same-tab refresh (needed, since processing can take a while) but is cleared when the tab closes and is never sent automatically like a cookie would be. A new tab opening the same report link falls back to a manual re-entry prompt. Residual exposure: `sessionStorage` is readable by any script running in the page's origin, so a successful XSS on the frontend origin *would* be able to read it — mitigated (not eliminated) by the app rendering no user-controlled HTML anywhere (SS1's XSS row).

## 3. Authorization — Full Test Matrix

All four document-scoped endpoints (`GET .../status`, `GET .../report`, `GET .../clauses/{id}/evidence`, `DELETE /v1/documents/{id}`) share one dependency, `require_document_access`, so a future endpoint cannot ship unauthenticated by accident. Tested this phase (`backend/tests/test_document_authorization.py`, `test_document_deletion.py`) against: correct token, wrong token, missing token, **malformed token (5 variants: no scheme, wrong scheme, empty-after-scheme, wrong-case scheme)**, another document's token, guessed document ID, nonexistent document, **nonexistent clause ID**, and a clause ID that belongs to a different document than the one authorized. Every failure mode returns an identical `access_denied` 404 body (aside from `request_id`) — proven by a dedicated test asserting body equality across causes, so no response can be used to enumerate valid IDs or distinguish "wrong token" from "no such document."

`POST /v1/documents` needs no authorization (it *creates* the credential) but is now rate-limited (SS5).

## 4. Dependency Audit

**Frontend (`npm audit`):** 0 vulnerabilities (re-confirmed Phase 11).

**Backend (`pip-audit` against `requirements.txt`):**

| Package | Installed | Advisories | Fixed in | Action |
|---|---|---|---|---|
| `chromadb` | 1.5.9 | PYSEC-2026-311 (pre-auth code injection via a chromadb *server's* HTTP API, `trust_remote_code`) | none published yet | **Accepted risk, not reachable.** This app only ever uses `chromadb.PersistentClient`/`EphemeralClient` (embedded, in-process) — never `HttpClient`, never `chromadb run`. Verified via repo-wide grep: zero references to any Chroma server-mode API. The vulnerable HTTP endpoint (`/api/v2/tenants/.../databases/...`) is never exposed by this application. Re-confirmed Phase 11: no newer chromadb version exists. |
| `starlette` | ~~0.41.3~~ **1.6.0 (Phase 11)** | 7 advisories, all closed by the Phase 11 upgrade | — | **Closed.** See `docs/PROVISIONAL_DECISIONS.md` P11.1 for the upgrade investigation (minimal justified jump, not blindly "latest") and verification (`pip-audit` post-upgrade flags zero starlette advisories). The Phase 10 content-type-gate mitigation for the one reachable finding (PYSEC-2026-249) is kept anyway as harmless defense-in-depth (`app/main.py`). |
| `pytest` | 8.3.4 | PYSEC-2026-1845 (predictable `/tmp/pytest-of-{user}` temp directory naming on UNIX; local-user privilege/DoS risk) | 9.0.3 | **Accepted risk, found Phase 11, not fixed.** Dev/test-only dependency — never imported or run by the deployed application; the vulnerable code path (pytest's own temp-directory creation during a test run) has no production reachability at all, regardless of hosting environment. The fix requires a pytest 8→9 major-version bump with no available in-range patch; per this phase's own "do not blindly run a broad dependency upgrade" discipline (`docs/PROVISIONAL_DECISIONS.md` P11.1), a major-version test-framework upgrade with its own breaking-change surface across a 700+-test suite is out of scope for a routine regression pass. Candidate for a future dedicated dependency-upgrade review, same as the FastAPI/Starlette upgrade was before Phase 11 executed it. |

**Why the starlette upgrade waited until Phase 11 despite being flagged in Phase 10:** every fix version was `>=1.0.0`, outside the range `fastapi==0.115.6` allowed (`<0.42.0`) — closing it required a coordinated FastAPI major-version upgrade, which needed its own dedicated, fully-tested phase rather than being bundled into Phase 10's security-hardening pass under "narrowly-scoped fix" discretion. Phase 11 was exactly that dedicated phase.

## 5. Resource Exhaustion / Rate Limiting (new this phase)

`ErrorCode.RATE_LIMITED` existed since early phases (defined, mapped to a safe message on both backend and frontend) but nothing ever raised it — Security_and_Privacy_v2.md SS8's "Upload rate limiting per session/IP" requirement was undelivered until this audit found the gap. Fixed: `app/core/rate_limit.py`, an in-process fixed-window counter (default 20 requests / 60 seconds per client IP), applied to `POST /v1/documents` only. Tested (`test_upload_rate_limit.py`): requests within the limit succeed, the request that exceeds it gets a 429 with the canonical error shape (never the numeric threshold itself, which would help an attacker tune around it), and the limiter doesn't interfere with unrelated read endpoints.

**Documented limitations, not solved this phase (MVP scope discipline, Security_and_Privacy_v2.md SS9):**
- Per-worker-process state only — a multi-worker or multi-instance deployment needs a shared store (Redis) for a true global limit.
- ~~No `X-Forwarded-For` trust configuration~~ — **closed in Phase 11**: `resolve_client_ip` (`rate_limit.py`) now honors `X-Forwarded-For` when `Settings.trust_proxy_headers=True` is explicitly set for a deployment that actually sits behind one trusted reverse proxy, trusting only the rightmost (proxy-observed) entry — never the client-spoofable leftmost one. Defaults to `False` (direct-peer IP only). See `docs/PROVISIONAL_DECISIONS.md` P11.5.
- ~~No automatic 90-day retention/deletion job~~ — **closed in Phase 11**: `backend/scripts/run_retention_cleanup.py` + `app/services/retention_service.py` (Security_and_Privacy_v2.md SS3); user-initiated deletion (SS7 below) and the automatic window now share the same underlying deletion function.

## 6. Grounding Guard — Adversarial Findings

Re-ran and extended the existing 19-scenario adversarial suite (`test_explanation_fidelity.py`) against every attack pattern in this phase's checklist: omitted claims, fabricated/altered amounts, altered dates/conditions/affected party, unsupported consequences, hidden facts outside `claims[]`, and claims that contradict the Risk Engine or assert safety/legality. All but two are correctly caught, and the third — basis-substitution — was closed this phase (see below).

**Two remaining documented, known limitations** (a purely lexical/token-based verifier's structural ceiling — Grounding_and_Evidence_Spec.md's own scope explicitly rules out building a full semantic NLP system):
1. **Conditionality changes** (`test_12`, found Phase 7.5) — a claim that drops a clause's conditional gating can still pass if descriptive vocabulary otherwise overlaps.
2. **Affected-party changes** (`test_07`, found and a fix reverted in Phase 7.5) — an explicit check was built, then reverted after it rejected an ordinary grounded paraphrase in the regression suite.

**Closed this phase: basis-substitution** (`test_18`, found by Phase 10, fixed by Phase 11) — a claim could reuse a clause's own vocabulary and a correctly-cited number while reattaching it to a different, unsupported basis (tested case: a clause's "2% of the outstanding principal" reworded as "2% of the borrower's monthly loan payment"), and pass because enough *other* incidental words overlapped. `grounding_guard.py` gained a fifth, additive check (`_basis_substitution_detected`, docs/PROVISIONAL_DECISIONS.md P11.6): a proximity-windowed comparison of the words immediately following a number's "of"/"per" governing phrase in the claim against the words following that same number's governing phrase(s) in the source — narrower and more targeted than check 4's whole-sentence bag-of-words overlap, and only ever active when the claim itself uses an explicit "of"/"per" construct. Verified with 11 new adversarial/regression cases (`test_grounding_guard_basis_sensitivity.py`, 8 named categories) and a full re-run of `corpus/eval/run_all.py`: zero regressions in the existing 19-scenario suite, DEV macro F1 unchanged at 1.00, TEST macro F1 unchanged at 0.54, `unsupported_factual_claim_rate` unchanged at 0.00%, `unsupported_claim_leak_count` unchanged at 0. A residual limitation of the fix itself is documented in P11.6 (very short/generic basis phrases — e.g. a bare "date" — can still share just enough vocabulary to slip through; not claimed to be closed).

None of the three original limitations, nor the fix that closed the third, ever allow an ungrounded HIGH/MEDIUM verdict, confidence, category, or evidence to be altered — only the *explanation prose* is affected, and even then only in the specific narrow ways above. The Risk Engine's own decision is never reachable from the LLM regardless (SS1).

## 7. Document Deletion (new this phase)

Security_and_Privacy_v2.md SS3 requires documents and all derived data be "deletable by the access-token holder on request" — no such endpoint existed before this phase. Added `DELETE /v1/documents/{id}` (`app/api/documents.py`), behind `require_document_access`. Cascades via existing `cascade="all, delete-orphan"` ORM relationships and `ondelete="CASCADE"` foreign keys through `clauses` → `clause_analyses` → `evidence_spans`/`financial_entities`/`matched_patterns`, plus the associated `processing_jobs` row, then best-effort removes the stored original file. Tested (`test_document_deletion.py`), including the specific, structurally-guaranteed property that **corpus/reference data is never reachable through this operation**: `matched_patterns.corpus_pattern_id` is `ondelete="RESTRICT"` and no relationship path exists from `documents` to `corpus_patterns` at all — verified directly (a corpus pattern referenced by a deleted document's matched pattern survives the deletion in the test).

Not built this phase: a UI affordance for deletion (out of scope — "do not add major product features") and the automatic retention-window purge job (SS5).

## 8. Logging Audit

Every log call in `backend/app` goes through `log_event()`, which enforces `ALLOWED_LOG_FIELDS` — confirmed structurally (not just by convention) by grepping for direct `logger.info/error/warning/debug/critical()` calls anywhere in the backend: **zero matches**. The allowlist excludes `raw_text`, evidence/entity/explanation content, prompts, and tokens by construction; a disallowed field is redacted, not silently dropped (visible in output as `[REDACTED:disallowed_field]`, so a mistake is loud, not silent). Phase 8's dedicated logging-safety test (`test_pipeline_logging_safety.py`) empirically captures a full pipeline run's actual formatted log output and asserts specific canary content never appears in it — re-confirmed passing this phase.

**Not independently verified against source this phase:** the `anthropic`/`httpx` SDK dependencies' own internal logging. Verified by architecture instead — the Anthropic API takes its key in a header (never a URL/query string) and clause content only in the POST body, and httpx's default INFO-level request logging emits only the request line (method + URL, no query string, no body) — but this claim rests on known httpx/SDK behavior, not a line-by-line audit of those libraries' source in this pass.

## 9. Frontend Security

No `dangerouslySetInnerHTML`, no raw `innerHTML` writes, no `document.write` anywhere in shipped frontend source (one `innerHTML` match found by grep was a test assertion *reading* rendered output, not a write). No analytics/tracking SDK is installed at all (`package.json` has zero such dependencies), so "document text sent to analytics" is structurally impossible, not just avoided. No `window.location`-based redirect logic exists anywhere (all navigation is `router.push()` to an internally-constructed, fixed path). `NEXT_PUBLIC_*` usage is confined to `config/env.ts` (API base URL and environment label only). `package.json`'s version string was bumped off the stale `0.0.0-phase0` placeholder.

## 10. What This Audit Did Not Do

- No external penetration test or red-team exercise.
- No SAST tool run (e.g., Semgrep, Bandit) — this was a manual, threat-model-driven review plus the two dependency scanners named above.
- No fuzz testing of the PDF/DOCX parsers against a corpus of malformed files beyond the existing unit tests' hand-crafted cases.
- No load/soak test with real concurrency or an external load-generation tool — SS12 below is a small, sequential, in-process smoke test only.
- No verification of the `anthropic`/`httpx` SDKs' own source for logging behavior (SS8).
- No infrastructure-level review (hosting platform, reverse proxy, TLS termination, network segmentation) — this repository has no deployment configuration of its own to review yet.

## 11. Tests Performed This Phase

674 backend tests pass (up from 666 before this phase's own additions: +5 malformed-token variants × 3 endpoints, +1 nonexistent-clause case, +7 deletion tests, +3 rate-limit tests, +4 content-type-gate tests, +2 grounding-adversarial tests, +2 smoke-load tests = +30 including the ones already counted mid-phase). Full list of new/expanded test files this phase:
- `test_document_authorization.py` (extended: malformed-token matrix, nonexistent-clause case)
- `test_document_deletion.py` (new)
- `test_upload_rate_limit.py` (new)
- `test_upload_content_type_gate.py` (new)
- `test_smoke_load.py` (new)
- `tests/services/test_explanation_fidelity.py` (extended: 2 new adversarial scenarios)

## 12. Deployment Recommendations

1. Set `cors_origins` to the real production frontend origin(s) — never leave it at the `localhost:3000` development default.
2. Set a real `ANTHROPIC_API_KEY` and a PostgreSQL `DATABASE_URL` — `Settings._validate_production_requirements` already fails startup loudly if either is missing/sqlite in production, but confirm this via a real production-mode boot before first deploy.
3. If deploying behind a reverse proxy, set `TRUST_PROXY_HEADERS=true` explicitly so the rate limiter resolves real client IPs from `X-Forwarded-For` instead of degrading to a single shared bucket (SS5, `docs/PROVISIONAL_DECISIONS.md` P11.5) — only do this when the proxy is genuinely trusted and directly in front of the app (exactly one hop); leave it `false` otherwise.
4. ~~Schedule a dedicated FastAPI/Starlette upgrade phase to close the remaining dependency advisories in SS4~~ — **done in Phase 11**: `fastapi==0.133.0`/`starlette==1.6.0`, all 7 starlette advisories closed per `pip-audit` (`docs/PROVISIONAL_DECISIONS.md` P11.1).
5. If/when this deploys with more than one worker process or more than one instance, revisit the rate limiter (SS5) and the background-pipeline concurrency model (still explicitly single-worker MVP per Technical_Architecture_v2.md SS9) — both currently assume in-process state.
6. ~~Consider a scheduled retention-purge job before this handles real user documents at any meaningful volume~~ — **done in Phase 11**: `backend/scripts/run_retention_cleanup.py` + `app/services/retention_service.py` implement the documented 90-day automatic window (Security_and_Privacy_v2.md SS3); still needs an operator to actually schedule it via external cron/platform scheduler at deploy time (see `docs/DEPLOYMENT_CHECKLIST.md`).

## 13. Phase 11 Addendum: Error-Monitoring Payload Safety

This repository has no external error-monitoring/crash-reporting integration (no Sentry, Rollbar, Bugsnag, Datadog, New Relic, or similar SaaS — confirmed by grep, zero matches for any of those names in `backend/app`). The only "error monitoring" that exists is the structured JSON stdout logging in `app/core/logging.py` plus the five FastAPI exception handlers in `app/core/errors.py`. Phase 11 re-reviewed every exception-adjacent `log_event` call site in `backend/app` (`errors.py`'s five handlers, `analysis_pipeline.py`'s pipeline/background-task failure paths, `generation_pipeline_service.py`'s generation-failure paths, `retention_service.py`'s cleanup-failure path, `risk_scoring_service.py`'s scoring-failure path) against the SS8 discipline already established in Phase 10, specifically checking for any place a raw exception message, `repr(exc)`, or traceback could reach either the logged payload or the client-facing `user_message`:

- Every site logs either a fixed string constant, `type(exc).__name__`, or a pre-vetted "safe machine label" value from a bounded, documented enum-like field (`LLMGenerationError.category`, `GenerationOutcome.failure_category`) — never `str(exc)`, `exc.args`, or a traceback. Grepped for `str(exc)`, `exc.args`, `traceback`, `exc_info=True`, and `logger.exception` across `backend/app`: zero matches (the only hits are code comments documenting this exact discipline).
- `handle_http_exception` (the `StarletteHTTPException` handler) forwards `exc.detail` into the client-facing `user_message` when it's a string — verified safe because the application itself never raises `HTTPException` anywhere (grepped, zero matches), so the only `StarletteHTTPException`s this handler ever sees are framework-generated ones (e.g. "Not Found" for an unmatched route), never one carrying application-internal detail.
- `handle_validation_error` (the `RequestValidationError` handler) never forwards `exc.errors()` — which can include a copy of submitted field values — into either the log or the response; both use a fixed generic message.
- `log_event`'s allowlist + 128-character length cap (`app/core/logging.py`) remains the structural backstop underneath all of the above: even a future mistake that tried to log a long/free-text value into an allowed field would be redacted (`[REDACTED:value_too_long]`), not silently accepted.

**Conclusion: no new gap found.** This is a confirmation, not a fix — the discipline already established in Phase 10 SS8 held up under a dedicated second look, including at three call sites (`analysis_pipeline.py`'s background-task handler, `retention_service.py`, and Phase 11's own new `metrics.py`/`health.py`) that didn't exist when SS8 was first written.
