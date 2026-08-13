"""Trigger / condition / consequence / affected-party extraction —
Technical_Architecture_v2.md SS3 ("Condition/consequence extraction ...
rule + pattern based"). No LLM (Phase 4 spec, design rule).

Deliberately conservative (Phase 4 spec SS13): every field defaults to
`None` and is only populated when the clause text contains an explicit,
recognized structural marker for it. A clause with no conditional
connective ("if", "should", "unless", ...) never gets an invented
`trigger` — see `test_condition_extraction.py`'s ambiguous-language cases.

Fields mirror `ClauseAnalysis.trigger/condition/consequence/affected_party`
(Risk_Taxonomy_and_Labeling_Spec.md SS6) exactly — same names, same
optionality — so the Risk Engine (Phase 5) can assign these straight onto
`clause_analyses` without translation.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Connectives that introduce a trigger/condition. Longer/more specific
# phrases are listed so they win over a shorter substring during regex
# alternation (first-match-wins), e.g. "in the event that" over a bare "in".
# PHASE_6.5: added "provided that", "subject to", "notwithstanding",
# "conditional on"/"conditional upon", "upon" (docs/PROVISIONAL_DECISIONS.md
# P6.6 item 4 — these three were previously unrecognized entirely). Bare
# "provided" is deliberately NOT added — it collides with cross-reference
# phrasing ("as provided in Section 7"), which must not be mistaken for a
# conditional trigger.
_TRIGGER_MARKERS = re.compile(
    r"\b(?:in\s+the\s+event\s+that|in\s+case|provided\s+that|subject\s+to|notwithstanding|"
    r"conditional\s+(?:on|upon)|if|should|where|when|upon)\b",
    re.IGNORECASE,
)
# "unless"/"except" introduce a *negative* conditional — still a trigger
# marker, just flagged separately so callers/tests can distinguish polarity
# if useful later; the extracted trigger text itself is unchanged.
# PHASE_6.5: broadened from "except\s+(?:where|that|if)" to bare "except" —
# the narrower phrase missed common exception phrasing like "except as ..."
# (adversarial Case E: "Except as provided in Section 7, no prepayment fee
# applies."). The trigger-start position is unaffected either way since the
# extracted trigger text is derived from the marker's start offset, not the
# marker text itself.
_NEGATIVE_TRIGGER_MARKERS = re.compile(r"\b(?:unless|except)\b", re.IGNORECASE)

# Words that mark the start of a temporal/threshold qualifier *within* a
# trigger span — splits "the event" from "the measurable condition on it",
# e.g. "remains unpaid" (trigger) vs "for more than 30 days" (condition).
_CONDITION_QUALIFIER = re.compile(
    r"\b(?:within|for\s+more\s+than|for\s+at\s+least|more\s+than|less\s+than|no\s+later\s+than|"
    r"after|before|in\s+excess\s+of|up\s+to)\b",
    re.IGNORECASE,
)

# Marks the start of the consequence when no comma boundary is usable.
_CONSEQUENCE_MARKER = re.compile(
    r"\b(?:then|shall|will|may|is\s+entitled\s+to|applies|becomes\s+due)\b",
    re.IGNORECASE,
)

_SENTENCE_SPLIT = re.compile(r"(?<=[.;])\s+")
# PHASE_6.5: a narrower variant used only for finding the sentence *start*
# before a trigger marker (`_sentence_start_before` below) — excludes a
# period immediately preceded by a short Title-case abbreviation ("Rs.",
# "Mr.", "No.", ...) so "An early termination fee of Rs. 5,000 applies if
# ..." doesn't get its pre-trigger consequence truncated at "Rs." as if that
# were a real sentence boundary. Deliberately not applied to `_SENTENCE_SPLIT`
# itself (the tail/consequence-end truncation), which has been correct as-is
# and is out of scope for this fix.
_SENTENCE_START_SPLIT = re.compile(r"(?<![A-Z][a-z]\.)(?<=[.;])\s+")
_CLAUSE_SPLIT = re.compile(r",\s*")

_PARTY_TERMS = (
    "the borrower",
    "the lender",
    "the policyholder",
    "the insurer",
    "the tenant",
    "the landlord",
    "the company",
    "the customer",
    "the insured",
    "either party",
    "both parties",
    "the borrower's",
)
_PARTY_PATTERN = re.compile("|".join(re.escape(p) for p in _PARTY_TERMS), re.IGNORECASE)

_MIN_CONSEQUENCE_CHARS = 8


@dataclass(frozen=True, slots=True)
class ExtractedCondition:
    trigger: str | None
    condition: str | None
    consequence: str | None
    affected_party: str | None
    is_negative_trigger: bool


def _find_affected_party(text: str) -> str | None:
    match = _PARTY_PATTERN.search(text)
    return match.group(0) if match else None


def _sentence_start_before(text: str, position: int) -> int:
    """Start offset of the sentence enclosing `position` — the end of the
    last `_SENTENCE_SPLIT` match strictly before `position`, or 0 if `position`
    is in the first sentence. Used to recover text *before* a trigger marker
    within its own sentence (PHASE_6.5 consequence-before-trigger fix below)."""
    start = 0
    for match in _SENTENCE_START_SPLIT.finditer(text, 0, position):
        start = match.end()
    return start


def _split_trigger_and_condition(span: str) -> tuple[str | None, str | None]:
    qualifier_match = _CONDITION_QUALIFIER.search(span)
    if qualifier_match is None:
        return (span.strip(" .,;") or None), None
    trigger = span[: qualifier_match.start()].strip(" .,;")
    condition = span[qualifier_match.start() :].strip(" .,;")
    if not trigger:
        # The qualifier appeared at the very start — nothing meaningful to
        # split; treat the whole span as the trigger rather than emit an
        # empty trigger with the qualifier duplicated as "condition".
        return (span.strip(" .,;") or None), None
    return trigger, (condition or None)


def extract_condition(clause_text: str) -> ExtractedCondition:
    """Deterministic, marker-based extraction. Returns all-`None` fields
    (except `affected_party`, which is searched independently) when no
    recognized trigger connective is present — never invents a chain from
    vague language (Phase 4 spec SS13).

    Structure: find the sentence containing the trigger marker; split that
    sentence on its first comma (trigger+condition *before* the comma,
    consequence *after*); if there's no comma, fall back to splitting on
    the first consequence-marker word found inside the sentence instead.
    The pre-comma (or pre-marker) portion is then further split into
    `trigger` vs `condition` on a qualifier word ("within", "for more
    than", ...), if one is present.

    PHASE_6.5 (docs/PROVISIONAL_DECISIONS.md P6.6 item 1): if neither of the
    above finds a consequence, the text *before* the trigger marker within
    its own sentence is used as a last-resort consequence — covers
    "X shall pay Y if Z" phrasing (consequence-before-trigger), not just
    "if Z, X shall pay Y" (trigger-before-consequence). Sentences where the
    trigger marker already opens the sentence have no such pre-trigger text,
    so this never changes previously-correct trigger-first extractions.
    """
    affected_party = _find_affected_party(clause_text)

    # Whichever marker — positive ("if"/"when"/"where"/...) or negative
    # ("unless"/"except where"/...) — appears *earliest* in the text wins.
    # A plain search-then-fallback order would let a positive marker like
    # bare "where" win over an earlier-starting "except where" simply
    # because positive markers were checked first, even though "except"
    # changes the polarity of that same "where".
    positive_match = _TRIGGER_MARKERS.search(clause_text)
    negative_match = _NEGATIVE_TRIGGER_MARKERS.search(clause_text)
    if positive_match is None and negative_match is None:
        return ExtractedCondition(
            trigger=None,
            condition=None,
            consequence=None,
            affected_party=affected_party,
            is_negative_trigger=False,
        )
    if negative_match is not None and (
        positive_match is None or negative_match.start() <= positive_match.start()
    ):
        trigger_match = negative_match
        is_negative = True
    else:
        assert positive_match is not None
        trigger_match = positive_match
        is_negative = False

    # The sentence that contains the trigger marker, from the marker
    # onward, trimmed to the next sentence boundary.
    tail = clause_text[trigger_match.start() :]
    sentence_end = _SENTENCE_SPLIT.search(tail)
    sentence = (tail[: sentence_end.start()] if sentence_end else tail).strip(" .;")

    comma_parts = _CLAUSE_SPLIT.split(sentence, maxsplit=1)
    if len(comma_parts) == 2 and len(comma_parts[1].strip(" .,;")) >= _MIN_CONSEQUENCE_CHARS:
        pre, consequence = comma_parts[0], comma_parts[1].strip(" .,;")
    else:
        pre = sentence
        consequence = None
        marker_match = _CONSEQUENCE_MARKER.search(pre)
        if marker_match is not None:
            candidate = pre[marker_match.start() :].strip(" .,;")
            if len(candidate) >= _MIN_CONSEQUENCE_CHARS:
                consequence = candidate
                pre = pre[: marker_match.start()].strip(" .,;")

    if consequence is None:
        sentence_start = _sentence_start_before(clause_text, trigger_match.start())
        pre_trigger_text = clause_text[sentence_start : trigger_match.start()].strip(" .,;")
        if len(pre_trigger_text) >= _MIN_CONSEQUENCE_CHARS:
            consequence = pre_trigger_text

    trigger, condition = _split_trigger_and_condition(pre)

    return ExtractedCondition(
        trigger=trigger,
        condition=condition,
        consequence=consequence,
        affected_party=affected_party,
        is_negative_trigger=is_negative,
    )
