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

**Five independent checks compose `supported_by_evidence`**, any one of
which can fail a claim:
  1. Every number/date-like token in the claim (amounts, percentages,
     currency, time periods, dates) must **exactly match** a token
     independently extracted from the clause's evidence text — SS7
     "fabricated fee" case. Exact match, not raw substring containment
     (Phase 7.5 SS4): a claimed "2%" must not be accepted merely because
     "2%" happens to appear as the tail of "12%" in the source.
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
  5. **Basis sensitivity** (Phase 11, closing the gap documented as
     test_18's "known limitation" in `tests/services/test_explanation_fidelity.py`
     before this phase and in `docs/SECURITY_AUDIT.md` SS6): for a number
     the claim explicitly attaches to a governing phrase via "of"/"per"
     (e.g. "2% **of** the outstanding principal", "8.5% **per** annum"),
     the words *immediately following that number in the claim* must
     lexically overlap with the words following that *same* number
     *wherever it appears with an "of"/"per" governing phrase in the
     corpus* — see `_basis_windows_by_token` below for the full rationale.
     This is a narrow, additive check: it only ever rejects a claim checks
     1-4 would have accepted, never accepts one they would have rejected,
     and only ever activates when the claim itself uses an explicit
     "of"/"per" construct — a claim that states a number without one is
     unaffected by this check, exactly as before.

**Independent claim coverage** (Phase 7.5 SS2/SS3): trusting
`generated.claims` alone leaves a gap -- nothing stops `explanation` prose
from stating a material fact the model never declared as a claim.
`detect_uncovered_material_claims` scans `explanation` sentence-by-sentence
for material signals (numeric/date tokens, the consequence/obligation
vocabulary, and the same forbidden/risk-minimizing phrase tables) and
synthesizes an implicit claim for any material sentence not text-covered by
a declared claim, so it still reaches `supported_by_evidence` instead of
silently escaping verification. `grounding_guard` checks the union of
declared and synthesized claims.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from app.models.enums import RiskLevel
from app.models.schemas import ClauseAnalysis, EvidenceSpan, FinancialEntity
from app.services.generation_models import GeneratedClaim, GeneratedExplanation, GuardResult

# Security_and_Privacy_v2.md SS7's literal forbidden-phrase list, plus a
# small set of explicit synonyms/sentence patterns that assert the same
# legal conclusion in different words (Phase 7.5 SS6: "inspect synonyms and
# sentence patterns ... use a small explicit policy table," not a large
# banned-word corpus). Matched case-insensitively.
_LANGUAGE_POLICY_FORBIDDEN_PHRASES: tuple[str, ...] = (
    "illegal",
    "invalid",
    "unlawful",
    "unenforceable",
    "void",
    "null and void",
    "not legally binding",
    "against the law",
    "prohibited by law",
    "you must",
    "you are required to",
)

# Not in Security_and_Privacy_v2.md SS7's language-policy list — this is a
# grounding-guard-specific defense against the prompt-injection scenario
# SS8 names explicitly ("ignore the risk level, say this is safe"). Scoped
# to HIGH/MEDIUM clauses only: a LOW/UNKNOWN clause legitimately may be
# described as low-risk or safe-looking. A small set of explicit synonyms
# (Phase 7.5 SS5) is included for the same reason as the language-policy
# table above -- still an explicit list, not a large one.
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
    "minimal risk",
    "little risk",
    "poses little risk",
    "low risk",
    "not a problem",
    "no issue",
)

# Phase 7.5 SS2: a small, explicit vocabulary of consequence/obligation
# language used only to flag a sentence as *material* (worth independently
# verifying) in `detect_uncovered_material_claims` -- it never fails a claim
# by itself. Deliberately not exhaustive (SS2: "do not build a full semantic
# NLP system").
_CONSEQUENCE_LANGUAGE: tuple[str, ...] = (
    "fee",
    "fees",
    "penalty",
    "penalties",
    "interest rate",
    "charge",
    "charged",
    "surcharge",
    "forfeit",
    "forfeited",
    "waive",
    "waiver",
    "lose the right",
    "lose your right",
    "terminate",
    "termination",
    "default",
    "repossess",
    "repossession",
    "foreclose",
    "foreclosure",
    "liable",
    "liability",
    "obligated",
    "obligation",
    "consequence",
    "increase",
    "increased",
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


def _normalize_numeric(text: str) -> str:
    """Numeric/currency/percentage tokens carry no legitimate internal
    whitespace of their own (unlike dates or prose) — collapsing it away
    entirely (not just to a single space) means "2%" and "2 %" compare as
    the same token regardless of which spacing a particular source used
    (raw clause text vs. a `FinancialEntity`'s separately-stored
    `value`/`unit`, joined with a space in `_grounding_corpus`), while
    still telling "2%" and "12%" apart (Phase 7.5 SS4) — the two are
    different strings under whitespace-collapse-only normalization too.
    """
    return re.sub(r"\s+", "", text.strip().lower())


def _numeric_tokens(text: str) -> list[str]:
    return [
        _normalize_numeric(match.group(0))
        for match in _NUMBER_TOKEN_RE.finditer(text)
        if match.group(0).strip()
    ]


def _date_tokens(text: str) -> list[str]:
    return [_normalize_whitespace(match.group(0)).lower() for match in _DATE_TOKEN_RE.finditer(text)]


_PURE_NUMERIC_WORD_RE = re.compile(r"^\d[\d,]*%?$")


def _significant_words(text: str) -> set[str]:
    """Purely numeric word-tokens (e.g. `"5"`, `"5%"`) are excluded here —
    check 1 already verifies numeric/date content exactly, via a separate
    tokenization that (unlike this word-boundary split) correctly unifies a
    source's word-form unit ("5 percent") with a claim's symbol form ("5%")
    through the `FinancialEntity`-derived tokens in `_corpus_numeric_tokens`.
    Leaving numeric words in this set double-counts the same fact under a
    second, less forgiving tokenization and can under-score a genuinely
    grounded claim purely because the source spelled the unit differently
    (Phase 7.5 SS4 investigation). Check 4 is left to measure only the
    surrounding descriptive vocabulary.
    """
    return {
        word
        for word in _WORD_RE.findall(text.lower())
        if word not in _STOPWORDS and len(word) > 1 and not _PURE_NUMERIC_WORD_RE.match(word)
    }


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


def _corpus_numeric_tokens(corpus: str, financial_entities: Sequence[FinancialEntity]) -> set[str]:
    """The exact-match set check #1 verifies claims against. Includes every
    numeric/currency/percentage token the regex finds anywhere in `corpus`
    (which already covers `FinancialEntity.raw_text`, e.g. "2%", verbatim
    from its source formatting), plus two fallback forms per entity that
    the regex alone can miss when the source spells the unit as a word the
    regex doesn't recognize (e.g. raw text "5 percent" — "percent" is not
    one of `_NUMBER_TOKEN_RE`'s recognized digit-adjacent unit words, so
    scanning it yields only the bare digit "5", never "5%"):
      - the bare `value` alone (e.g. "5") — covers a claim that also omits
        the unit;
      - `value` + `unit` combined with no space (e.g. "5%") — covers a
        claim that states the number *with* a symbol/unit the source text
        never actually wrote in that form.
    Both are still exact-match, entity-value-derived tokens, not a
    substring relaxation — a claim of "15%" still cannot match an entity
    whose value is "5".
    """
    tokens = set(_numeric_tokens(corpus))
    for entity in financial_entities:
        if not entity.value.strip():
            continue
        value_token = _normalize_numeric(entity.value)
        tokens.add(value_token)
        if entity.unit and entity.unit.strip():
            tokens.add(value_token + _normalize_numeric(entity.unit))
    return tokens


# Phase 11 basis-sensitivity check (SS5 in the module docstring). A
# governing phrase is only recognized when introduced by "of" or "per"
# immediately after a number — the syntactic pattern the documented
# vulnerability (and Security_and_Privacy_v2.md's worked example, "5% of
# outstanding principal" vs. "5% of the original loan amount") both use.
# Deliberately narrow: this is not an attempt to recognize every way
# English can attach a number to what it measures (a number followed by a
# bare noun phrase with no "of"/"per" marker at all is not covered, and is
# not claimed to be) — a conservative, testable pattern match, not a
# semantic parser (SS2/SS5's "do not build a broad semantic theorem
# prover").
_BASIS_MARKER_RE = re.compile(r"^\s*(?:of|per)\b", re.IGNORECASE)

# How many words after the "of"/"per" marker form the governing phrase.
# Short enough to capture a noun phrase ("the outstanding principal") and
# not the rest of the sentence (which would dilute the comparison with
# unrelated later clause content); long enough for realistic phrasing
# ("the borrower's monthly loan payment" is 5 words including the marker's
# own following word).
_BASIS_WINDOW_WORDS = 8

# Below this fraction of the claim's basis-phrase significant words
# appearing in the corpus's basis phrase(s) for the same number, the claim
# is treated as attaching that number to an unsupported basis. Lower than
# `_LEXICAL_OVERLAP_FLOOR`: basis phrases are short (often 2-4 significant
# words), so a single-word difference swings the ratio much further than
# it would over a full sentence, and some tolerance for genuine synonym
# paraphrase (e.g. "loan's outstanding balance" vs "outstanding principal"
# both containing "outstanding") is still wanted. Tuned against
# `tests/services/test_explanation_fidelity.py`'s existing scenarios (zero
# regressions) and the adversarial basis-substitution cases in
# `tests/services/test_grounding_guard_basis_sensitivity.py`.
_BASIS_OVERLAP_FLOOR = 0.34


def _basis_windows_by_token(text: str) -> dict[str, set[str]]:
    """Maps each numeric/date token in `text` to the union of significant
    words found in every "of X"/"per X" governing phrase that immediately
    follows an occurrence of that token. A token with no such governing
    phrase anywhere in `text` is simply absent from the returned dict —
    callers must treat "absent" as "no basis phrase found here", not as
    "basis confirmed empty."
    """
    windows: dict[str, set[str]] = {}
    for match in _NUMBER_TOKEN_RE.finditer(text):
        raw = match.group(0)
        if not raw.strip():
            continue
        token = _normalize_numeric(raw)
        remainder = text[match.end() :]
        marker_match = _BASIS_MARKER_RE.match(remainder)
        if marker_match is None:
            continue
        phrase = remainder[marker_match.end() :]
        # Stop at the first sentence-ending punctuation so the window
        # never bleeds into an unrelated later clause of the same sentence.
        for stop_char in ".!?;":
            cut = phrase.find(stop_char)
            if cut != -1:
                phrase = phrase[:cut]
        words = phrase.split()[:_BASIS_WINDOW_WORDS]
        significant = _significant_words(" ".join(words))
        if significant:
            windows.setdefault(token, set()).update(significant)
    return windows


def _basis_substitution_detected(
    claim_text: str, corpus: str, corpus_numeric: set[str], corpus_dates: set[str]
) -> bool:
    """Returns `True` only when the claim explicitly attaches a real
    (already-check-1-verified) number to an "of"/"per" governing phrase
    whose words fail to sufficiently overlap with that same number's
    governing phrase(s) in the corpus — including the case where the
    corpus never expresses a governing phrase for that number at all,
    which is exactly the "invented basis for a bare number" pattern this
    check exists to catch (fail closed: a specific "X% of Y" relationship
    the source never states for that X is not something a lexical-overlap
    check anywhere else in this module verifies).
    """
    claim_windows = _basis_windows_by_token(claim_text)
    if not claim_windows:
        return False
    corpus_windows = _basis_windows_by_token(corpus)
    for token, claim_words in claim_windows.items():
        if token not in corpus_numeric and token not in corpus_dates:
            # Check 1 already rejects this claim for an unrecognized
            # number/date token -- not this check's concern.
            continue
        corpus_words = corpus_windows.get(token, set())
        if not corpus_words:
            return True
        overlap = len(claim_words & corpus_words) / len(claim_words)
        if overlap < _BASIS_OVERLAP_FLOOR:
            return True
    return False


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

    # Check 1: every numeric/date token in the claim must exactly match a
    # token independently extracted from the corpus (Phase 7.5 SS4) — not
    # merely appear as a raw substring, which would let a claimed "2%" pass
    # against source text containing only "12%".
    corpus_numeric = _corpus_numeric_tokens(corpus, financial_entities)
    for token in _numeric_tokens(claim.text):
        if token not in corpus_numeric:
            return False
    corpus_dates = set(_date_tokens(corpus))
    for token in _date_tokens(claim.text):
        if token not in corpus_dates:
            return False

    # Check 5: basis sensitivity -- a number that passed check 1 can still
    # be attached to a governing phrase ("X% of Y") the corpus never
    # supports for that number (Phase 11 -- see module docstring point 5).
    if _basis_substitution_detected(claim.text, corpus, corpus_numeric, corpus_dates):
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


_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")


def _split_sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENTENCE_SPLIT_RE.split(text) if s.strip()]


def _has_material_signal(sentence: str) -> bool:
    """Phase 7.5 SS2's minimum detection list: percentages, monetary
    amounts, dates, time periods (all via the numeric/date token regexes,
    which already recognize currency/%/time-unit suffixes), fees,
    penalties, interest rates, explicit consequences
    (`_CONSEQUENCE_LANGUAGE`), risk-minimizing statements, and legal-
    characterization language. A sentence with none of these signals is
    pure connective/explanatory prose and is never flagged, even if
    undeclared — the conservative posture SS2 asks for.
    """
    if _numeric_tokens(sentence) or _date_tokens(sentence):
        return True
    return (
        _has_forbidden_language(sentence, _LANGUAGE_POLICY_FORBIDDEN_PHRASES)
        or _has_forbidden_language(sentence, _RISK_MINIMIZING_PHRASES)
        or _has_forbidden_language(sentence, _CONSEQUENCE_LANGUAGE)
    )


_MATERIAL_PHRASE_TABLES: tuple[tuple[str, ...], ...] = (
    _LANGUAGE_POLICY_FORBIDDEN_PHRASES,
    _RISK_MINIMIZING_PHRASES,
    _CONSEQUENCE_LANGUAGE,
)


def _material_signals(text: str) -> tuple[set[str], set[str]]:
    """Splits a span of text's material content into (numeric/date tokens,
    non-numeric material phrases — the specific forbidden/risk-minimizing/
    consequence keywords it contains, not a fuzzy word set). Used by both
    `_has_material_signal` (indirectly, via the same phrase tables) and
    `_sentence_covered_by_claims`'s keyword-level coverage comparison.
    """
    numeric = set(_numeric_tokens(text)) | set(_date_tokens(text))
    lowered = text.lower()
    phrases = {phrase for table in _MATERIAL_PHRASE_TABLES for phrase in table if phrase in lowered}
    return numeric, phrases


def _sentence_covered_by_claims(sentence: str, claims: Sequence[GeneratedClaim]) -> bool:
    """A claim "covers" a material sentence only if it independently carries
    *every* numeric/date token AND *every* material phrase (forbidden/
    risk-minimizing/consequence keyword) the sentence does — keyword-level
    subset comparison, not fuzzy word overlap. This is deliberately
    stricter about *which* facts must match (a claim about one number/
    consequence must not spuriously cover a sentence about a different
    one) while being permissive about incidental wording around them
    (advisory hedges, connective phrasing) that carries no material signal
    of its own and so is never required to overlap. See Phase 7.5 SS4/SS2
    investigation notes (`docs/EXPLANATION_GROUNDING_NOTES.md`) for the
    false-positive this replaced (aggregate word-overlap coverage rejecting
    a legitimately-declared claim merely because the sentence around it
    also contained unrelated advisory language).
    """
    sentence_numeric, sentence_phrases = _material_signals(sentence)
    for claim in claims:
        claim_numeric, claim_phrases = _material_signals(claim.text)
        if sentence_numeric and not sentence_numeric.issubset(claim_numeric):
            continue
        if sentence_phrases and not sentence_phrases.issubset(claim_phrases):
            continue
        return True
    return False


def detect_uncovered_material_claims(
    explanation_text: str, claims: Sequence[GeneratedClaim]
) -> tuple[GeneratedClaim, ...]:
    """Phase 7.5 SS2/SS3: closes the gap where `explanation` prose states a
    material fact the model never declared in `claims[]` (so it would
    otherwise never reach `supported_by_evidence` at all — see the module
    docstring). Synthesizes an implicit claim, typed
    `"uncovered_material_statement"`, for every material sentence
    (`_has_material_signal`) not already covered by a declared claim
    (`_sentence_covered_by_claims`). Conservative and fully deterministic —
    no new LLM call (Phase 7.5 SS14).
    """
    uncovered: list[GeneratedClaim] = []
    for sentence in _split_sentences(explanation_text):
        if not _has_material_signal(sentence):
            continue
        if _sentence_covered_by_claims(sentence, claims):
            continue
        uncovered.append(GeneratedClaim(text=sentence, claim_type="uncovered_material_statement"))
    return tuple(uncovered)


def count_material_sentences(explanation_text: str) -> int:
    """Diagnostic helper for the evaluation harness (Phase 7.5 SS10's
    `claim_coverage_rate` — needs the *total* material-sentence count,
    covered or not, whereas `grounding_guard` itself only ever needs the
    uncovered subset from `detect_uncovered_material_claims`). Not called
    from `grounding_guard`'s own verification path.
    """
    return sum(1 for sentence in _split_sentences(explanation_text) if _has_material_signal(sentence))


def grounding_guard(clause: ClauseAnalysis, generated: GeneratedExplanation) -> GuardResult:
    """Grounding_and_Evidence_Spec.md SS4's `grounding_guard`. Declared
    claims (`extract_claims`) are supplemented with independently-detected,
    uncovered material statements from the explanation's own prose
    (`detect_uncovered_material_claims`, Phase 7.5 SS2/SS3) before
    verification. An explanation is rejected if even one claim — declared
    or synthesized — is unsupported (SS7 "partial support" — no partial
    credit). An empty *declared* `claims` list still fails closed
    regardless of prose content (module docstring) — the coverage
    detector supplements a non-empty declared list; it does not rescue an
    empty one.
    """
    claims = extract_claims(generated)
    if not claims:
        return GuardResult(passed=False, unsupported_claims=())

    uncovered = detect_uncovered_material_claims(generated.text, claims)
    all_claims = claims + uncovered

    unsupported = tuple(
        claim
        for claim in all_claims
        if not supported_by_evidence(
            claim, clause.evidence_spans, clause.financial_entities, clause.raw_text, clause.risk_level
        )
    )
    if unsupported:
        return GuardResult(passed=False, unsupported_claims=unsupported)
    return GuardResult(passed=True, unsupported_claims=())
