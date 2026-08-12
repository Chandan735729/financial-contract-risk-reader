# Grounding and Evidence Spec

**Cross-references:** AI_Risk_Engine_Design.md, Risk_Taxonomy_and_Labeling_Spec.md (schema), Dataset_and_Evaluation_Spec.md (metrics), Technical_Architecture_v2.md

---

## 1. Principle

Evidence is not a UI nicety attached after the fact — it is produced as part of the Risk Engine's reasoning (AI_Risk_Engine_Design.md) and verified before anything is displayed. The LLM's role is strictly to explain an already-evidenced, already-scored decision in plain language; it is never the source of a risk claim, a financial figure, or a legal characterization that isn't already present in `evidence_spans` or `financial_entities`.

## 2. Evidence Extraction

For each candidate signal contributing to a clause's risk score (retrieval match, rule hit, extracted entity, extracted condition), the Evidence Engine records an `EvidenceSpan`:

```json
{"text": "string", "start_char": int, "end_char": int, "page_number": int}
```

**Verification requirement (non-negotiable):** every `EvidenceSpan.text` must be mechanically confirmed as a substring (allowing minor whitespace/punctuation normalization) of the clause's `raw_text` at the moment it's created — not just trusted from wherever it was extracted. An evidence span that can't be verified this way is discarded, not shown, and the signal it supported is down-weighted or excluded from scoring (it cannot contribute to `HIGH`/`MEDIUM` risk without at least one verified span, per PRD_v2.md Product Principle 5).

Evidence answers, per clause, wherever the text supports it:
- What triggered the risk? → `trigger` + its evidence span
- What condition activates it? → `condition` + its evidence span
- What happens? → `consequence` + its evidence span
- Who is affected? → `affected_party`
- What financial amount was detected? → `financial_entities[]`, each with its own evidence span

## 3. Claim Verification (Citation Correctness)

Distinct from span verification (Section 2, which checks *extracted* evidence against source text), claim verification checks the **generated explanation** against both the evidence spans and the source clause text as a whole:

1. Parse the LLM's structured output into discrete claims (e.g., sentence-level or fact-level segments).
2. For each claim, check whether it is supported by: (a) the `evidence_spans` already attached to this clause, (b) the `financial_entities` already extracted, or (c) a direct near-verbatim match elsewhere in `raw_text`.
3. A claim introducing a fact, number, date, or consequence **not present** in any of the above is flagged as unsupported.

This is stricter than v1's grounding guard (which only checked a single `cited_span`) — v2 checks the explanation's claims comprehensively against the structured evidence already produced upstream, since the explanation is now expected to reference specific entities and conditions, not just paraphrase a clause.

## 4. Grounding Guard — Design

```python
def grounding_guard(clause: ClauseAnalysis, generated: GeneratedExplanation) -> GuardResult:
    claims = extract_claims(generated.text)
    unsupported = []
    for claim in claims:
        if not supported_by_evidence(claim, clause.evidence_spans, clause.financial_entities, clause.raw_text):
            unsupported.append(claim)

    if unsupported:
        return GuardResult(passed=False, unsupported_claims=unsupported)
    return GuardResult(passed=True, unsupported_claims=[])
```

**What the LLM must NOT invent** (enforced by both prompt design and this guard): penalties, fees, dates, legal conclusions ("this is illegal/unenforceable" — see Security_and_Privacy_v2.md §7 language policy), obligations, or financial consequences not already present in the clause's extracted entities/evidence. The prompt supplies the Risk Engine's already-decided `risk_level`, `risk_category`, `evidence_spans`, and `financial_entities` as fixed input and instructs the model to explain, not to add new risk facts.

## 5. Hallucination Handling & Fallback

If `grounding_guard` returns `passed=False`:
- The explanation is **not shown** to the user under any circumstance, per PRD_v2.md Product Principle 6.
- One automatic retry is attempted with a stricter prompt reminder (explicitly listing the unsupported claims and instructing the model to remove them).
- If the retry also fails the guard, the clause falls back to a defined safe state: the risk level, category, confidence, and raw evidence spans are still shown (these came from the Risk Engine, not the LLM, so they remain trustworthy), but the plain-language explanation field shows: *"We identified this as a [risk_level] [category] concern based on the evidence below, but couldn't generate a verified plain-language explanation. Please review the original text."*
- This event is logged as a `grounding_failure` in the error analysis framework (Dataset_and_Evaluation_Spec.md §7), tracked as a rate over time — a rising rate signals a prompt or generation-service issue to fix, not something to quietly tolerate.

## 6. Citation Design (What the User Sees)

Every displayed explanation is paired, in the UI, with its supporting evidence spans rendered as **highlighted excerpts of the original clause text**, not just a link or footnote — so the user can see the exact source language next to the plain-English claim it supports, without needing to trust the pairing blindly. Financial entities (extracted amounts/percentages/rates) are shown as distinct, separately-highlighted inline elements within the evidence excerpt, since these are often the single most decision-relevant detail (Frontend_Specification_v2.md §5).

## 7. Tests (Required Before Any Generation-Service Change Ships)

- **Positive control:** a clause with a clean, fully-evidenced explanation passes the guard.
- **Negative control (fabricated fee):** a deliberately constructed case where the model output includes a monetary amount not present in the clause — guard must catch this.
- **Negative control (fabricated legal conclusion):** model output claims a clause is "illegal" or "unenforceable" — guard (combined with the language-policy check, Security_and_Privacy_v2.md §7) must catch and block this regardless of whether the underlying risk assessment was otherwise correct.
- **Partial support case:** explanation is mostly grounded but includes one invented detail — guard must still fail the whole explanation (no partial credit; a single unsupported claim disqualifies display, since users can't tell which parts to trust otherwise).
- **Near-verbatim tolerance case:** explanation paraphrases evidence with minor wording differences — guard must still pass this (avoiding false rejections that would make the fallback trigger too often and erode usefulness).

These five cases form the minimum regression suite; they are run on every change to the generation prompt or the guard logic itself, and their pass/fail status is part of the release gate alongside the metrics in Dataset_and_Evaluation_Spec.md §8.
