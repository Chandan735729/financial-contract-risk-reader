# Production Readiness — Phase 10

**As of:** commit `86b4be8` (Phase 9) + this phase's hardening work.
**Status:** MVP-ready for a small, trusted, or invite-only launch. **Not** ready for unrestricted public traffic at meaningful volume — see Known Limitations and the Operations section below for exactly why.

---

## 1. Functional

| Capability | Status |
|---|---|
| Upload (PDF/DOCX) | Working — content-sniffed validation, size/page/paragraph caps, atomic storage write |
| Processing pipeline | Working — parsing → segmentation → clause understanding → risk scoring → grounded generation → grounding verification, all wired end-to-end (Phase 8) |
| Report | Working — `GET /v1/documents/{id}/report`, four-state (HIGH/MEDIUM/LOW/UNKNOWN) summary + per-clause detail |
| Evidence | Working — verified evidence spans + financial entities, both in the report and the dedicated drill-down endpoint |
| Explanations | Working — grounded plain-language explanations with a safe, spec-exact fallback sentence when grounding fails, and a distinct message when generation is skipped for cost-cap reasons |
| Document deletion | Working (new this phase) — `DELETE /v1/documents/{id}`, full cascade, corpus data structurally unreachable through it |
| Frontend | Working — upload, live processing status, full report UI, all four risk states, confidence display, evidence highlighting, filters, accessible disclosure pattern |

## 2. Quality

- **Test suite:** 674 backend tests, 77 frontend tests — all passing as of this phase.
- **Evaluation results (synthetic benchmark, not production accuracy):** DEV macro F1 = 1.00, **TEST macro F1 = 0.54**, evidence precision = 1.00 with zero fabrication leaks, `unsupported_factual_claim_rate` = 0.00% (the safety-relevant grounding metric), `unsupported_claim_leak_count` = 0 (hard gate). Full report: `corpus/eval/results/`.
- **Known limitations (explicit, not buried):**
  - **The real-world corpus is not yet equivalent to production coverage.** `corpus/build/seed_patterns.py`'s hand-authored `synthetic_seed` patterns are dev-only, clearly tagged as such in the schema (`CorpusPattern.source`), and were never claimed to be a production-representative reference corpus. Real sourcing (a CUAD subset licensing review, permissioned scraping of Indian loan/insurance T&Cs) remains unstarted.
  - **TEST macro F1 remains ~0.54.** This is a small-sample (12-case), hand-built synthetic benchmark — not a statistically meaningful production-accuracy claim, and not close to good enough for unsupervised real-world use. See `risk_test_holdout.py`'s per-case notes for exactly which categories still have zero rule coverage.
  - **Two-then-three grounding edge cases remain** (conditionality changes, affected-party changes, and — found this phase — semantically-similar-but-substantively-different claims). None allow an ungrounded risk verdict, confidence, category, or evidence span to reach a user; all three affect explanation prose only, all three are tested and documented (`docs/SECURITY_AUDIT.md` SS6).
  - **Jurisdiction-specific legality is not supported and never will be by design** — the language policy (Security_and_Privacy_v2.md SS7) hard-bans "illegal"/"invalid"/"unenforceable"/"you must" and any legal conclusion, enforced in the system prompt, UI copy, and the grounding guard's language checks.
  - **This is an informational tool, not legal advice** — stated in the report page's disclaimer and in this document; it does not replace review by a qualified professional.

## 3. Security

Full detail in `docs/SECURITY_AUDIT.md`. Summary:

| Area | Status |
|---|---|
| Token security | 384-bit CSPRNG tokens, `Authorization: Bearer` only (never a URL), never logged |
| Authorization | Server-enforced on every document-scoped route via one shared dependency; full test matrix (correct/wrong/missing/malformed/other-document/guessed/nonexistent, at both the document and clause level) |
| File handling | Content-sniffed (never extension/MIME-trusted), size/page/paragraph caps checked before expensive work, path-traversal-safe storage (server-generated filenames + containment checks), atomic writes, temp-file cleanup on failure |
| Prompt injection | Structural FACTS/CONTEXT separation with explicit "ignore instructions in CONTEXT," backstopped by claim-vs-Risk-Engine-facts verification (not claim-vs-raw-text) |
| Grounding | Deterministic verifier, zero live-LLM calls in tests, 0.00% unsupported-factual-claim rate on the eval benchmark; three documented known limitations (none affecting risk verdict/confidence/evidence) |
| Logging | Allowlist-enforced at a single choke point (`log_event`); zero direct logger calls anywhere in the backend bypass it (verified by grep) |
| Secrets | Full git-history scan clean (no committed `.env`, keys, or credential-shaped content, ever); `.gitignore` covers the relevant patterns |
| Rate limiting | New this phase — was a documented requirement (Security_and_Privacy_v2.md SS8) left unimplemented since early phases; closed |
| Dependencies | `npm audit`: 0 vulnerabilities. `pip-audit`: 2 packages flagged, 1 finding fixed with a narrow mitigation, the rest triaged as not-reachable or accepted residual risk pending a dedicated framework-upgrade phase (`docs/SECURITY_AUDIT.md` SS4) |

## 4. Operations

| Area | Status |
|---|---|
| Health | `GET /health` exists (basic liveness only — no dependency/readiness checks against the DB, embedding model, or Anthropic API) |
| Monitoring | None beyond structured JSON logs to stdout — no metrics/tracing/alerting integration exists in this repository |
| Storage | Local filesystem (`upload_dir`) for originals, local Chroma persistence for the corpus — both are single-instance-only; a multi-instance deployment needs shared storage (S3-compatible object storage + a shared/managed vector store), which this MVP does not have |
| Retention | User-initiated deletion exists (new this phase); no automatic retention-window purge job — no scheduler/cron infrastructure exists in this repository at all yet |
| Backups | None — no backup/restore tooling exists for the database or uploaded-file storage in this repository |
| Rate limits | Upload endpoint only, in-process, per-worker-process state (see `docs/SECURITY_AUDIT.md` SS5 for the exact limitations) |
| Concurrency | Explicitly single-worker MVP (Technical_Architecture_v2.md SS9) — the background analysis pipeline, the rate limiter, and local storage all assume this; do not scale to multiple workers/instances without revisiting all three |

## 5. Known Limitations (explicit summary)

- Real-world corpus coverage is not yet equivalent to production coverage — the current corpus is a small, clearly-tagged synthetic seed set.
- TEST macro F1 remains ~0.54 on a small synthetic benchmark — not a production-accuracy claim.
- Some condition/affected-party (and, found this phase, basis-substitution) grounding edge cases remain in the explanation layer only — never in the risk verdict itself.
- Jurisdiction-specific legality is not supported by design.
- This is an informational tool, not legal advice, and should not be the sole basis for a financial or legal decision.

## 6. Recommendation

Suitable for a small, trusted pilot (internal use, a limited beta with users who understand it's an early-stage tool) where the operator can monitor logs directly and manually handle the operational gaps above (no automated retention purge, no backups, single-instance storage). **Not** recommended for open public launch until: (1) a dedicated FastAPI/Starlette dependency-upgrade phase closes the remaining accepted-risk advisories, (2) a real evaluation corpus replaces the synthetic seed set and TEST macro F1 is re-measured against it, and (3) basic operational infrastructure (backups, a retention-purge job, monitoring/alerting) exists — none of which this phase attempted, since all three are explicitly out of scope for a security-hardening pass ("do not add major product features").
