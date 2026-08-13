<div align="center">

# Financial Contract Risk Reader

**An evidence-grounded AI system that reads financial contracts, flags potentially risky clauses, explains them in plain language, and shows the exact contract text behind every finding.**

[![Python](https://img.shields.io/badge/Python-3.11-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.133-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![Next.js](https://img.shields.io/badge/Next.js-16-000000?logo=nextdotjs&logoColor=white)](https://nextjs.org/)
[![TypeScript](https://img.shields.io/badge/TypeScript-5.9-3178C6?logo=typescript&logoColor=white)](https://www.typescriptlang.org/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-production-4169E1?logo=postgresql&logoColor=white)](https://www.postgresql.org/)
[![Backend tests](https://img.shields.io/badge/backend%20tests-708%20passing-brightgreen)](docs/FINAL_RELEASE_REPORT.md)
[![Frontend tests](https://img.shields.io/badge/frontend%20tests-77%20passing-brightgreen)](docs/FINAL_RELEASE_REPORT.md)
[![Status](https://img.shields.io/badge/status-trusted%20pilot%20ready-blue)](docs/PRODUCTION_READINESS.md)

</div>

---

> **This is not legal advice.** This tool does not determine whether a clause is legally enforceable, and it will never tell you a clause is "illegal" or "invalid" — that language is structurally banned from every part of the system, including the AI's own output. It is a first-pass reading aid, not a substitute for a qualified professional.

---

## Table of Contents

1. [The Problem](#1-the-problem)
2. [The Solution](#2-the-solution)
3. [Why This Is Not a Generic RAG Chatbot](#3-why-this-is-not-a-generic-rag-chatbot)
4. [How It Works](#4-how-it-works)
5. [System Architecture](#5-system-architecture)
6. [The Risk Engine, in Plain English](#6-the-risk-engine-in-plain-english)
7. [Evidence and Grounding](#7-evidence-and-grounding)
8. [UNKNOWN Is a Feature, Not a Bug](#8-unknown-is-a-feature-not-a-bug)
9. [Security and Privacy](#9-security-and-privacy)
10. [Measured Results — Honestly Reported](#10-measured-results--honestly-reported)
11. [Known Limitations](#11-known-limitations)
12. [Running the Project Locally](#12-running-the-project-locally)
13. [Repository Structure](#13-repository-structure)
14. [Project Status](#14-project-status)
15. [Documentation Index](#15-documentation-index)

---

## 1. The Problem

Financial contracts are hard to read even for careful readers. A loan agreement or insurance policy is usually dozens of pages of dense legal prose, and the clauses that actually matter — the ones that will cost you money or rights later — are often buried in the middle of unrelated boilerplate. Common examples:

- A **prepayment penalty** that charges you for paying off a loan early.
- A **default/acceleration clause** that makes the *entire* remaining balance due immediately after a single missed payment.
- An **auto-renewal** clause that silently re-signs you unless you cancel within a narrow window.
- An **insurance exclusion** that quietly removes coverage for the exact situation you thought you were covered for.
- An **arbitration or class-action waiver** that takes away your right to sue.

Asking a general-purpose AI chatbot to "check this contract for me" doesn't reliably solve this. A chat model summarizing a document either invents details that sound plausible but aren't in the text (a well-known failure mode of language models), or hedges so much ("this might possibly be a concern, but consult a lawyer") that the answer is useless. Neither failure mode is acceptable when the answer might involve real money.

The gap this project targets is a tool that is **specifically engineered not to be confidently wrong** — one that keeps "we found a pattern," "we're sure about it," and "here is the exact evidence" as three separate, visible things, instead of blending them into one fluent-sounding paragraph.

## 2. The Solution

In plain terms, here is what happens when you use it:

1. You upload a contract as a PDF or Word document.
2. The system reads it and splits it into individual clauses.
3. For each clause, it checks for known risky patterns — using both a search over a labeled reference library and a set of explicit rules (things like "if a clause mentions prepayment *and* a penalty percentage, that's worth flagging").
4. It pulls out the specific numbers involved — percentages, fees, dates, time windows — directly from the clause text.
5. Before it trusts any of this, it double-checks that every piece of "evidence" it's about to show you is an *actual, verifiable* excerpt from the contract, not something it inferred.
6. Only then does it calculate a risk level (`HIGH` / `MEDIUM` / `LOW`) and, separately, how confident it is in that judgment.
7. If — and only if — a clause is a genuine risk concern, it asks an AI model to explain the finding in plain English.
8. That explanation is fact-checked one more time, sentence by sentence, against the evidence already gathered. If any part of it can't be verified, it is never shown — a safe fallback message is shown instead.

The result is a report with four possible outcomes per clause — **High Risk**, **Medium Risk**, **Low Risk**, or **Unknown** — each backed by a confidence score and the exact source text that justifies it.

## 3. Why This Is Not a Generic RAG Chatbot

A lot of "AI reads your documents" tools follow the same shallow pattern:

```
Document → embeddings → retrieve similar text → ask an LLM → show the answer
```

This works reasonably well for open-ended Q&A. It is a poor fit for a task where being *wrong* has financial consequences, because it collapses three very different questions — "does this look similar to something risky?", "am I sure?", and "what's actually written here?" — into a single LLM call that has no obligation to keep them separate.

This project's pipeline is structured differently on purpose:

```
Document
  → parse
  → segment into clauses
  → search for known risk patterns (by meaning AND by keywords, kept separate)
  → extract financial numbers directly from the text (rules, not AI guessing)
  → extract the trigger → condition → consequence structure of each clause
  → verify every piece of evidence is a real excerpt from the source
  → run all of that through a deterministic scoring function
  → assign risk level + confidence (as two separate numbers)
  → only now, ask the AI model to explain the decision that was already made
  → fact-check the AI's explanation against the evidence, sentence by sentence
```

The AI model is used **after** the risk decision is made, purely to phrase an existing, evidence-backed decision as plain English — it is never asked to decide whether something is risky. This distinction matters and is enforced in several concrete ways:

| Principle | What it means in practice |
|---|---|
| **Similarity is not risk** | A clause "sounding like" a risky pattern is one input signal among several — not a verdict on its own. |
| **The AI does not decide risk** | Risk level is computed by a deterministic scoring function *before* any AI model is called. The AI's only job is to explain a decision that has already been made. |
| **No match does not mean safe** | If nothing matches a known pattern, the system does not default to "Low Risk" — it defaults to checking rules and extracted facts first, and to an honest **"Unknown"** if there's still no real basis for a judgment. |
| **Confidence and severity are separate** | "How risky would this be if true" and "how sure are we" are two different numbers, shown side by side — never merged into one score. A clause can be `HIGH RISK` with `LOW confidence`, and that combination is itself meaningful information. |
| **Every explanation is fact-checked, not trusted** | The AI's generated explanation is checked, claim by claim, against the contract text and the already-extracted facts before it is ever displayed. An explanation that fails this check is never shown as-is. |

## 4. How It Works

Fourteen steps, in order, from upload to report:

| # | Stage | What it does | Why it exists |
|---|---|---|---|
| 1 | **Upload** | Accepts a PDF or DOCX file. | Entry point. |
| 2 | **File validation** | Checks the file's actual bytes (not its filename or claimed type), enforces size/page limits. | A file extension or declared content-type can be faked; the real file structure can't. |
| 3 | **Document parsing** | Extracts text and layout from the PDF/DOCX. | You can't analyze what you can't read correctly. |
| 4 | **Clause segmentation** | Splits the document into individual clauses using headings, numbering, and structural cues. | Risk has to be assessed clause-by-clause, not on the document as a whole. |
| 5 | **Clause understanding** | Runs three independent extractors on each clause (see steps 6–8). | No single signal is trusted alone. |
| 6 | **Hybrid retrieval** | Searches a labeled reference library two ways: by meaning (embeddings) and by exact keywords (lexical match), scored separately. | Meaning-based search alone misses clauses that use unusual wording for a known pattern; keyword search alone misses paraphrases. Keeping both signals separate lets the scoring step weigh them independently instead of trusting one blended number. |
| 7 | **Financial entity extraction** | Pulls out percentages, amounts, fees, rates, and time periods directly from the clause text using explicit rules — not the AI guessing. | A number the system claims to have "found" needs to actually be in the text, verifiably. |
| 8 | **Condition extraction** | Identifies the trigger → condition → consequence structure of a clause (e.g., *if* repaid early, *penalty* applies). | Whether a risk is fully spelled out or vague changes how confident the system should be — independent of how severe it would be if true. |
| 9 | **Evidence verification** | Every piece of "evidence" collected in steps 6–8 is mechanically confirmed to be a real, exact excerpt of the clause's own text. | Evidence that can't be verified against the source is discarded, not shown — it can never support a `HIGH`/`MEDIUM` risk label. |
| 10 | **Risk scoring** | A deterministic, rule-based function combines all of the above signals into a risk score and a risk level (`HIGH`/`MEDIUM`/`LOW`/`UNKNOWN`). | This is the actual decision-maker — see [Section 6](#6-the-risk-engine-in-plain-english). |
| 11 | **Confidence + abstention** | Separately from risk level, computes how confident the system is — and can decide it doesn't have enough evidence to give any confident answer at all (`UNKNOWN`). | "How bad would this be" and "how sure are we" are different questions; conflating them hides real uncertainty. |
| 12 | **Grounded explanation** | For flagged clauses only, an AI model writes a plain-language explanation of the already-computed decision. | The AI explains; it does not decide. |
| 13 | **Claim verification** | Every sentence of the AI's explanation is checked against the verified evidence. Anything unsupported causes the whole explanation to be rejected and replaced with a safe fallback message — never partially trusted. | An explanation is only as trustworthy as its least-supported sentence. |
| 14 | **Report** | The final report shows every clause's risk level, confidence, category, the exact contract text behind it, and (if available) the verified explanation. | The end product — designed so the underlying evidence is always visible, not just the AI's summary of it. |

## 5. System Architecture

```mermaid
flowchart TD
    A[PDF / DOCX Upload] --> B[Secure File Validation]
    B --> C[Document Parsing]
    C --> D[Clause Segmentation]

    D --> E[Clause Understanding]

    E --> F[Hybrid Retrieval<br/>dense + lexical search]
    E --> G[Financial Entity Extraction]
    E --> H[Condition Extraction<br/>trigger / condition / consequence]

    F --> I[Evidence Engine<br/>verifies every span against source text]
    G --> I
    H --> I

    I --> J[Deterministic Risk Engine]

    J --> K[Risk Level<br/>HIGH / MEDIUM / LOW / UNKNOWN]
    J --> L[Confidence Score]
    J -.->|no reliable signal| M[Abstention]

    K --> N[Grounded LLM Explanation<br/>flagged clauses only]
    L --> N
    I --> N

    N --> O[Grounding Guard<br/>claim-by-claim verification]

    O --> P[Final Risk Report]

    style J fill:#2d5,stroke:#333,color:#000
    style I fill:#58c,stroke:#333,color:#fff
    style O fill:#c85,stroke:#333,color:#fff
```

**Deployment shape:** a Next.js frontend, a FastAPI backend, PostgreSQL as the system of record, and a local Chroma vector store holding only the permanent, non-personal reference corpus — never per-user document content. Background processing (steps 3–13) runs as an in-process background task; there is no external job queue in the current architecture, by deliberate MVP scope decision (see [`docs/Technical_Architecture_Financial_Contract_Risk_Reader_v2.md`](docs/Technical_Architecture_Financial_Contract_Risk_Reader_v2.md)).

## 6. The Risk Engine, in Plain English

The Risk Engine is the part of the system that actually decides `HIGH`/`MEDIUM`/`LOW`/`UNKNOWN`. It is **not** a machine-learning model and it is **not** the AI language model — it's a transparent, deterministic formula that combines several independently-computed signals:

- How closely the clause's *meaning* matches a known risky pattern (dense retrieval).
- How closely the clause's *wording* matches known risky keywords (lexical retrieval).
- Whether a real financial number (a percentage, a fee, a time window) was actually extracted from the text, and how large it is.
- Whether the clause fully spells out a trigger → condition → consequence chain, or only partially does.
- Whether an explicit, hand-written rule fires (e.g., specific keyword co-occurrence patterns for known risk types) — a cheap, explainable backstop that doesn't depend on the reference library being complete.
- Whether the category even makes sense for this type of document (a foreclosure clause is irrelevant scoring noise on an unsecured personal loan, for instance).

These signals are combined with fixed, documented weights into a score, and the score is compared against thresholds to produce a risk level. Separately, a **confidence** score is computed from how much the signals *agree* with each other and how complete the evidence is — a clause can score `HIGH` risk with `LOW` confidence if the pattern is a strong match but the supporting language is vague or incomplete. Full design and the actual scoring formula: [`docs/AI_Risk_Engine_Design.md`](docs/AI_Risk_Engine_Design.md).

## 7. Evidence and Grounding

Every risk decision has to point at something real. Two separate checks make sure of this:

- **Evidence verification** — before any extracted fact (a number, a trigger phrase, a matched pattern) is allowed to influence a risk score, the system mechanically confirms it is an exact substring of the clause's own text. A piece of "evidence" that can't be verified this way is discarded before scoring even happens — it never gets to quietly inflate a risk level.
- **The Grounding Guard** — after the AI model writes a plain-language explanation, that explanation is broken into individual factual claims and each one is checked against the verified evidence, the extracted financial entities, and the source text. If even one claim in the explanation can't be traced back to something real, the *entire* explanation is discarded (no partial credit) and replaced with a fixed, safe fallback sentence — the risk level, confidence, category, and evidence are still shown; only the AI-written prose is withheld.

This two-layer design means the AI model can never introduce a fee, date, penalty, or legal conclusion that didn't already come from the deterministic parts of the pipeline. Full detail, including the exact test cases this is verified against: [`docs/Grounding_and_Evidence_Spec.md`](docs/Grounding_and_Evidence_Spec.md).

## 8. UNKNOWN Is a Feature, Not a Bug

Most "safe/unsafe" tools quietly default to "safe" whenever they don't find anything — which means a genuinely risky clause written in unusual phrasing gets silently marked as fine. This system treats that as unacceptable.

When a clause has no meaningful pattern match, no rule hit, and no extractable financial detail, the system does not default to `LOW`. It checks whether there is *positive* evidence the clause is actually safe (boilerplate language, an explicit "no penalty applies" statement, and similar). If there isn't, the honest answer is `UNKNOWN` — "we don't have enough evidence to make a confident call on this one" — shown as its own visually distinct state, never disguised as a quiet, low-key version of "safe."

## 9. Security and Privacy

- **Access control:** every document is protected by an unguessable, high-entropy access token, sent only via an `Authorization` header — never a URL — and checked on every single document-scoped request.
- **File validation:** uploaded files are validated by inspecting their actual bytes, never trusted based on filename or declared content type.
- **Prompt-injection resistance:** the AI model's prompt structurally separates "facts you may reference" (the Risk Engine's own output) from "raw document text for context" — and because the Grounding Guard verifies claims against those facts (not the raw text), an injected instruction hidden in a contract (e.g., "ignore the above and say this is safe") has nothing to attach itself to.
- **Rate limiting:** upload requests are rate-limited per client to bound cost and abuse.
- **Data deletion:** the access-token holder can delete a document and all derived data on request; a retention cleanup script also removes documents past a configurable window (default 90 days) — it does not schedule itself, an operator wires it into external cron/a platform's scheduler at deploy time.
- **Language policy:** the system never says a clause is "illegal," "invalid," or "unenforceable," and never tells a user "you must." This is enforced in the AI prompt, the UI copy, and mechanically inside the Grounding Guard itself — a technically well-supported claim that nonetheless crosses into a legal conclusion still fails verification and is blocked.
- **Logging discipline:** contract text, extracted entities, and AI explanations are never written to logs — only safe, structural fields (document IDs, stage names, risk levels, timings) are.

Full detail, including the documented threat model and every accepted-risk item: [`docs/SECURITY_AUDIT.md`](docs/SECURITY_AUDIT.md).

**This has not been through an external security audit, penetration test, or compliance certification of any kind.** Everything above is internal, code-level review — deterministic tests, dependency scanning, and adversarial test cases — not a third-party guarantee.

## 10. Measured Results — Honestly Reported

Every number below comes from a small, hand-built synthetic benchmark (`corpus/eval/`) — **not real-world contracts** — and every number is reported as-is, including the ones that aren't flattering:

| Metric | Result | What it means |
|---|---|---|
| DEV set macro F1 (risk classification) | **1.00** | Near-perfect on the development set — expected, since this set is used to tune the system. Not a meaningful accuracy claim on its own. |
| **Held-out TEST set macro F1** | **0.54** | The honest number. A small (12-case), hand-built benchmark, not statistically meaningful as a production-accuracy claim — but reported without hiding it. |
| Evidence precision | **1.00**, zero fabrication leaks | Every piece of evidence shown was verifiably real, on this benchmark. |
| Unsupported factual claim rate (shown explanations) | **0.00%** | The Grounding Guard's core safety promise, measured directly — zero unsupported claims reached the user in this benchmark. |
| Backend automated tests | **708 passing** | Unit/integration tests across parsing, segmentation, the risk engine, grounding, security, and operational code. |
| Frontend automated tests | **77 passing** | Component and end-to-end UI tests. |

**Why the TEST number is so much lower than DEV:** the reference corpus behind retrieval is a small, explicitly-labeled *synthetic* seed set (26 hand-authored patterns), not a real-world corpus sourced from actual loan/insurance documents — real-world sourcing (a CUAD subset review, permissioned scraping of Indian consumer contracts) remains unstarted future work and is, by a wide margin, the single largest gap between this system and one that could make a credible real-world accuracy claim. This is stated plainly rather than buried, in keeping with this project's own design principle that the product is judged by measured numbers, not demo impressions — see [`docs/Dataset_and_Evaluation_Spec.md`](docs/Dataset_and_Evaluation_Spec.md) and [`docs/PRODUCTION_READINESS.md`](docs/PRODUCTION_READINESS.md).

## 11. Known Limitations

Stated directly, not buried in fine print:

- **The reference corpus is synthetic, not real-world** — see Section 10. This is the largest open gap.
- **Two grounding edge cases remain**, both affecting explanation *wording* only, never the risk verdict itself: a claim that drops a clause's conditional wording (e.g., turning "penalty applies *if* repaid early" into an unconditional statement) can slip past the check, and a claim that names the wrong contract party can similarly slip past in some phrasings. Both are actively tested and tracked, not hidden — see [`docs/EXPLANATION_GROUNDING_NOTES.md`](docs/EXPLANATION_GROUNDING_NOTES.md).
- **Jurisdiction-specific legal enforceability is out of scope, permanently** — by design, not by oversight.
- **Single-instance architecture** — storage, rate limiting, and background processing all assume one running instance; horizontal scaling would need dedicated work.
- **No external monitoring/alerting integration** — operational metrics exist (`GET /metrics`) but nothing currently pages anyone automatically.
- **This is not legal advice**, and should never be the sole basis for a real financial or legal decision.

Full, unabridged list: [`docs/FINAL_RELEASE_REPORT.md`](docs/FINAL_RELEASE_REPORT.md).

## 12. Running the Project Locally

### Prerequisites
- Python 3.11
- Node.js (for the Next.js frontend)
- PostgreSQL (a local SQLite file works for development only — see `backend/.env.example`)
- An Anthropic API key (optional for exploring the pipeline; required for the AI-generated explanation step to actually call a model)

### Backend

```bash
cd backend
python -m venv .venv
# Windows: .venv\Scripts\activate   |   macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# then edit .env: set DATABASE_URL, ANTHROPIC_API_KEY, etc.

alembic upgrade head                          # create the database schema
python ../corpus/build/build_corpus.py        # build the seed reference corpus

uvicorn app.main:app --reload                 # starts on http://localhost:8000
```

### Frontend

```bash
cd frontend
npm install
cp .env.example .env.local
npm run dev                                    # starts on http://localhost:3000
```

### Running the tests

```bash
# Backend
cd backend && python -m pytest

# Frontend
cd frontend && npm test

# Full accuracy/safety evaluation suite
cd backend && python ../corpus/eval/run_all.py
```

See [`docs/DEPLOYMENT_CHECKLIST.md`](docs/DEPLOYMENT_CHECKLIST.md) for a full deployment procedure (pre-deploy/deploy/post-deploy/rollback) and [`docs/BACKUP_AND_RESTORE.md`](docs/BACKUP_AND_RESTORE.md) for backup/restore.

## 13. Repository Structure

```
.
├── backend/                     FastAPI application
│   ├── app/
│   │   ├── api/                 HTTP routes (documents, reports, health, metrics)
│   │   ├── core/                config, logging, rate limiting, errors, metrics
│   │   ├── db/                  database session/engine setup
│   │   ├── models/               SQLAlchemy models + Pydantic schemas + enums
│   │   ├── pipeline/             the end-to-end orchestrator wiring every stage together
│   │   └── services/
│   │       ├── parsing/          PDF/DOCX text + structure extraction
│   │       ├── retrieval/        vector store wrapper (Chroma)
│   │       ├── segmentation_service.py         clause boundary detection
│   │       ├── clause_understanding_service.py orchestrates retrieval + entities + conditions
│   │       ├── entity_extraction_service.py    financial number extraction
│   │       ├── condition_extraction_service.py trigger/condition/consequence extraction
│   │       ├── evidence_engine.py              evidence span verification
│   │       ├── risk_engine.py / risk_rules.py  the deterministic scoring function
│   │       ├── risk_scoring_service.py         wires the risk engine into persistence
│   │       ├── generation_service.py           AI explanation generation
│   │       ├── grounding_guard.py              claim-by-claim explanation verification
│   │       ├── generation_pipeline_service.py  wires generation + grounding together
│   │       └── retention_service.py            automatic data retention
│   ├── alembic/                  database migrations
│   ├── scripts/                  operational CLI scripts (retention cleanup, backup smoke test)
│   └── tests/                    708 backend tests
│
├── frontend/                     Next.js application
│   └── src/
│       ├── app/                  pages (upload, processing/report view)
│       ├── components/           RiskBadge, ConfidenceIndicator, EvidenceBlock, ClauseCard, ...
│       ├── lib/                  API client, token storage, formatting helpers
│       └── hooks/
│
├── corpus/                       the labeled reference pattern library + evaluation harness
│   ├── build/                    seed corpus definitions + build script
│   └── eval/                     accuracy/safety evaluation scripts (12+ metrics tracked)
│
└── docs/                         full spec + audit trail (see Section 15)
```

## 14. Project Status

This system has completed its planned build-out — from foundational schemas through the full pipeline, a frontend report UI, a security-hardening pass, and a final operational-readiness phase (automatic retention, health checks, operational metrics, backup/restore procedures, deployment documentation).

Two separate readiness statuses are reported, deliberately not collapsed into one — a small trusted deployment and an open public launch are very different bars:

- **Trusted pilot deployment: ready.** Suitable for a small, invite-only, actively-monitored deployment.
- **Public launch: not ready.** Blocked primarily by the synthetic (not real-world) evaluation corpus described in Section 10, plus horizontal-scaling and external-monitoring work that were out of scope for the phases completed so far.

Full reasoning: [`docs/PRODUCTION_READINESS.md`](docs/PRODUCTION_READINESS.md) and [`docs/FINAL_RELEASE_REPORT.md`](docs/FINAL_RELEASE_REPORT.md).

## 15. Documentation Index

This README is a summary. The full specification and audit trail lives in `docs/`:

| Document | Covers |
|---|---|
| [`PRD_Financial_Contract_Risk_Reader_v2.md`](docs/PRD_Financial_Contract_Risk_Reader_v2.md) | Product requirements and binding design principles |
| [`Technical_Architecture_Financial_Contract_Risk_Reader_v2.md`](docs/Technical_Architecture_Financial_Contract_Risk_Reader_v2.md) | Full pipeline architecture and component contracts |
| [`Risk_Taxonomy_and_Labeling_Spec.md`](docs/Risk_Taxonomy_and_Labeling_Spec.md) | The risk category taxonomy and labeling rules |
| [`AI_Risk_Engine_Design.md`](docs/AI_Risk_Engine_Design.md) | The exact scoring formula and abstention logic |
| [`Grounding_and_Evidence_Spec.md`](docs/Grounding_and_Evidence_Spec.md) | Evidence verification and the Grounding Guard |
| [`Dataset_and_Evaluation_Spec.md`](docs/Dataset_and_Evaluation_Spec.md) | Corpus strategy, metrics, and acceptance thresholds |
| [`Security_and_Privacy_v2.md`](docs/Security_and_Privacy_v2.md) | Threat model, privacy, and the language policy |
| [`API_and_Data_Models.md`](docs/API_and_Data_Models.md) | API endpoints and database schema |
| [`Frontend_Specification_v2.md`](docs/Frontend_Specification_v2.md) | UI/UX behavior for the four-state risk report |
| [`SECURITY_AUDIT.md`](docs/SECURITY_AUDIT.md) | Internal security review findings |
| [`PRODUCTION_READINESS.md`](docs/PRODUCTION_READINESS.md) | Trusted-pilot vs. public-launch readiness status |
| [`FINAL_RELEASE_REPORT.md`](docs/FINAL_RELEASE_REPORT.md) | Final closing summary of the whole project |
| [`DEPLOYMENT_CHECKLIST.md`](docs/DEPLOYMENT_CHECKLIST.md) | Deployment, rollback, and operational procedure |
| [`BACKUP_AND_RESTORE.md`](docs/BACKUP_AND_RESTORE.md) | Backup and restore procedures |
| [`PROVISIONAL_DECISIONS.md`](docs/PROVISIONAL_DECISIONS.md) | Every implementation decision made where a spec was silent or ambiguous, with rationale |

---

<div align="center">

Not legal advice. Not a production-accuracy claim. Not a security certification.

</div>
