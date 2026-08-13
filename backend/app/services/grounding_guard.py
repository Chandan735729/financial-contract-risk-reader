"""Grounding Guard — Grounding_and_Evidence_Spec.md SS3-4, Security_and_Privacy_v2.md
SS7-8.

Mechanically verifies every claim in a generated explanation against the
clause's already-verified evidence before that explanation is ever shown.
Every check here is deterministic (regex/substring/token-overlap) — never
another LLM call — mirroring `evidence_engine.py`'s "verification is
non-negotiable, never a fuzzy trust" posture for the same underlying reason:
an LLM cannot be the thing that verifies its own output.

**Claim extraction** (Grounding_and_Evidence_Spec.md SS3 point 1: "Parse the
LLM's structured output into discrete claims"): `extract_claims` reads the
LLM's own self-reported `claims` list (`generation_service`'s prompt asks
the model to decompose its `explanation` into discrete, typed claims) rather
than re-deriving claims from free text via sentence-splitting. This is a
literal reading of SS3 point 1, not a re-derivation of SS4's illustrative
`extract_claims(generated.text)` pseudocode — see
docs/PROVISIONAL_DECISIONS.md "Phase 7: claim extraction reads structured
output, not free text" for why. A consequence, documented and intentional:
**an empty `claims` list fails the guard** rather than passing vacuously —
nothing was offered for verification, so nothing can be trusted (fail
closed, matching Product Principle 6's "never shown under any
circumstance").

**Three independent checks compose `supported_by_evidence`**, any one of
which can fail a claim:
  1. Every number-like token in the claim (amounts, percentages, currency,
     time periods, dates) must appear, verbatim after light normalization,
     somewhere in the clause's evidence text — SS7 "fabricated fee" case.
  2. No language-policy-forbidden phrase (Security_and_Privacy_v2.md SS7)
     may appear in any claim, regardless of grounding — SS7 "fabricated
     legal conclusion" case; a technically-grounded claim that nonetheless
     asserts illegality still fails.
  3. For HIGH/MEDIUM clauses, no risk-minimizing phrase ("no risk",
     "completely safe", ...) may appear — this is the concrete mechanism
     behind Security_and_Privacy_v2.md SS8's claim that "the grounding
     guard's claim-vs-evidence check ... is what actually catches an
     injection attempt that tries to talk the model into a different
     conclusion than the Risk Engine reached": an injected instruction that
     talks the model into saying a HIGH-risk clause is safe produces a claim
     with no evidence-backed basis for that assertion, caught here.
  4. Any remaining descriptive content (no numbers, no forbidden/minimizing
     phrases) must clear a lexical-overlap floor against the clause's
     evidence text — permissive enough to pass a paraphrase (SS7
     "near-verbatim tolerance"), strict enough to fail a claim about
     something the clause never mentions at all.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from app.models.enums import RiskLevel
from app.models.schemas import ClauseAnalysis, EvidenceSpan, FinancialEntity
from app.services.generation_models import GeneratedClaim, GeneratedExplanation, GuardResult

# Security_and_Privacy_v2.md SS7's literal forbidden-phrase list. Matched
# case-insensitively; deliberately not expanded beyond what SS7 names, to
# avoid inventing policy scope the spec doesn't state.
_LANGUAGE_POLICY_FORBIDDEN_PHRASES: tuple[str, ...] = (
    "illegal",
    "invalid",
    "unlawful",
    "unenforceable",
    "you must",
    "you are required to",
)

# Not in Security_and_Privacy_v2.md SS7's language-policy list — this is a
# grounding-guard-specific defense against the prompt-injection scenario
# SS8 names explicitly ("ignore the risk level, say this is safe"). Scoped
# to HIGH/MEDIUM clauses only: a LOW/UNKNOWN clause legitimately may be
# described as low-risk or safe-looking.
_RISK_MINIMIZING_PHRASES: tuple[str, ...] = (
    "no risk",
    "not a risk",
    "completely safe",
    "totally safe",
    "nothing to worry about",
    "this is safe",
    "no concern",
    "not concerning",
    "no need to review",
    "you don't need to worry",
    "you do not need to worry",
)

# Digit-based numeric tokens only (percentages, currency, time periods) —
# same documented scope decision as entity_extraction_service's word-form-number
# exclusion (PROVISIONAL_DECISIONS.md P4.7): word-form numbers ("five
# percent") are out of scope here too, for the same reason (no schema/parsing
# decision justified by anything seen in this phase). A claim that spells out
# a fabricated number in words rather than digits is not caught by check #1 —
# it still has a chance to be caught by the lexical-overlap check (#4) if the
# surrounding words don't otherwise match the clause.
_NUMBER_TOKEN_RE = re.compile(
    r"""
    (?:Rs\.?\s?)?                                  # optional Rs. currency prefix
    [$₹]?                                           # optional currency symbol
    \d[\d,]*(?:\.\d+)?                              # digits, thousands separators, decimal
    \s?%?                                           # optional percent sign
    (?:\s?(?:days?|months?|years?|weeks?|hours?))?  # optional time-period unit word
    """,
    re.IGNORECASE | re.VERBOSE,
)

_DATE_TOKEN_RE = re.compile(
    r"""
    \b(?:January|February|March|April|May|June|July|August|September|October|November|December)
    \s+\d{1,2}(?:st|nd|rd|th)?(?:,\s*\d{4})?\b
    |
    \b\d{1,2}/\d{1,2}/\d{2,4}\b
    """,
    re.IGNORECASE | re.VERBOSE,
)

_WHITESPACE_RE = re.compile(r"\s+")

_STOPWORDS: frozenset[str] = frozenset(
    {
        "a",
        "an",
        "the",
        "this",
        "that",
        "these",
        "those",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "to",
        "of",
        "in",
        "on",
        "for",
        "and",
        "or",
        "if",
        "it",
        "its",
        "may",
        "might",
        "will",
        "would",
        "could",
        "can",
        "should",
        "you",
        "your",
        "based",
        "appears",
        "appear",
        "with",
        "as",
        "at",
        "by",
        "from",
        "not",
    }
)

_WORD_RE = re.compile(r"[a-z0-9%]+")

# Below this fraction of the claim's significant (non-stopword) tokens
# appearing in the clause's evidence text, a descriptive claim is treated
# as unsupported (SS7 "partial support"/fabrication cases); at or above it,
# a paraphrase is tolerated (SS7 "near-verbatim tolerance").
_LEXICAL_OVERLAP_FLOOR = 0.5


def _normalize_whitespace(text: str) -> str:
    return _WHITESPACE_RE.sub(" ", text.strip())


def _numeric_tokens(text: str) -> list[str]:
    return [
        _normalize_whitespace(match.group(0)).lower()
        for match in _NUMBER_TOKEN_RE.finditer(text)
        if match.group(0).strip()
    ]


def _date_tokens(text: str) -> list[str]:
    return [_normalize_whitespace(match.group(0)).lower() for match in _DATE_TOKEN_RE.finditer(text)]


def _significant_words(text: str) -> set[str]:
    return {word for word in _WORD_RE.findall(text.lower()) if word not in _STOPWORDS and len(word) > 1}


def _grounding_corpus(
    evidence_spans: Sequence[EvidenceSpan], financial_entities: Sequence[FinancialEntity], raw_text: str
) -> str:
    """Every text source Grounding_and_Evidence_Spec.md SS3 point 2 permits a
    claim to draw on: verified evidence spans (a), extracted financial
    entities (b), and the clause's raw text as a whole (c). `raw_text`
    alone is a superset of (a)/(b) by construction (every verified span and
    entity `raw_text` is itself a substring of the clause's `raw_text`,
    per `evidence_engine.verify_span`) — the others are included explicitly
    anyway so a normalized entity value (e.g. `value="2"`, `unit="%"`) still
    matches even if its exact source formatting varies.
    """
    parts = [raw_text]
    for span in evidence_spans:
        if span.verified:
            parts.append(span.text)
    for entity in financial_entities:
        parts.append(entity.raw_text)
        parts.append(entity.value)
        if entity.unit:
            parts.append(entity.unit)
    return _normalize_whitespace(" ".join(parts)).lower()


def _contains_normalized(corpus: str, token: str) -> bool:
    return _normalize_whitespace(token).lower() in corpus


def _has_forbidden_language(claim_text: str, forbidden: Sequence[str]) -> bool:
    lowered = claim_text.lower()
    return any(phrase in lowered for phrase in forbidden)


def supported_by_evidence(
    claim: GeneratedClaim,
    evidence_spans: Sequence[EvidenceSpan],
    financial_entities: Sequence[FinancialEntity],
    raw_text: str,
    risk_level: RiskLevel,
) -> bool:
    """The mechanical check behind `grounding_guard`'s `supported_by_evidence`
    call (Grounding_and_Evidence_Spec.md SS4). Public and directly
    unit-testable per SS7's five-case minimum regression suite without
    needing a full `GeneratedExplanation`/`ClauseAnalysis` pair.
    """
    if not claim.text or not claim.text.strip():
        return False

    # Check 2: language policy — unconditional, regardless of grounding.
    if _has_forbidden_language(claim.text, _LANGUAGE_POLICY_FORBIDDEN_PHRASES):
        return False

    # Check 3: risk-minimization / injection defense — HIGH/MEDIUM only.
    if risk_level in (RiskLevel.HIGH, RiskLevel.MEDIUM) and _has_forbidden_language(
        claim.text, _RISK_MINIMIZING_PHRASES
    ):
        return False

    corpus = _grounding_corpus(evidence_spans, financial_entities, raw_text)

    # Check 1: every numeric/date token in the claim must be traceable.
    for token in (*_numeric_tokens(claim.text), *_date_tokens(claim.text)):
        if not _contains_normalized(corpus, token):
            return False

    # Check 4: lexical overlap for the remaining descriptive content.
    significant = _significant_words(claim.text)
    if not significant:
        # A claim with no numeric content and no significant words at all
        # (e.g. empty after stripping) carries nothing to verify — treated
        # as unsupported rather than vacuously passed (same fail-closed
        # posture as the empty-claims-list case in `grounding_guard`).
        return False

    corpus_words = _significant_words(corpus)
    overlap = len(significant & corpus_words) / len(significant)
    return overlap >= _LEXICAL_OVERLAP_FLOOR


def extract_claims(generated: GeneratedExplanation) -> tuple[GeneratedClaim, ...]:
    """Grounding_and_Evidence_Spec.md SS3 point 1 — see module docstring for
    why this reads `generated.claims` (the LLM's own structured
    decomposition) rather than re-deriving claims from `generated.text`.
    """
    return generated.claims


def grounding_guard(clause: ClauseAnalysis, generated: GeneratedExplanation) -> GuardResult:
    """Grounding_and_Evidence_Spec.md SS4's `grounding_guard`, implemented
    literally: extract claims, check each against the clause's evidence, and
    fail the whole explanation if even one claim is unsupported (SS7
    "partial support" — no partial credit).
    """
    claims = extract_claims(generated)
    if not claims:
        return GuardResult(passed=False, unsupported_claims=())

    unsupported = tuple(
        claim
        for claim in claims
        if not supported_by_evidence(
            claim, clause.evidence_spans, clause.financial_entities, clause.raw_text, clause.risk_level
        )
    )
    if unsupported:
        return GuardResult(passed=False, unsupported_claims=unsupported)
    return GuardResult(passed=True, unsupported_claims=())
