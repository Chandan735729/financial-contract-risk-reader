"""Financial entity extraction — Technical_Architecture_v2.md SS3 ("Entity
Extraction Service ... rule/regex-based, LLM-assisted only as a fallback,
never sole source"). Phase 4 spec SS10 explicitly excludes an LLM fallback
for this phase — extraction here is deterministic regex/number-parsing only.

Extraction is deliberately kept separate from interpretation
(Phase 4 spec SS9): "5% of outstanding principal" is extracted as a
`percentage` entity with `value="5"`, never silently turned into a computed
rupee amount — no financial calculation happens here.

`extraction_confidence` on `ExtractedEntity` is *extraction* confidence
(how unambiguous the pattern match itself was), never clause risk
confidence (Phase 4 spec SS11) — deterministic regex matches that need no
disambiguation get a fixed 1.0; only the amount/fee keyword-proximity
disambiguation (see `_classify_currency_context`) uses a lower value, since
that step is inference beyond the literal pattern match. Not a calibrated
probability — no calibration benchmark exists for this (Phase 4 spec SS11).
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.models import db_models
from app.models.schemas import FinancialEntityType

# ==================================================================
# Patterns
# ==================================================================

# Rate/time-period qualifiers that turn a bare percentage into a `rate`
# (Phase 4 spec SS9 examples: "18% p.a.", "2% per month"). PHASE_6.5: added
# "quarterly"/"per quarter" — the existing set covered annum/month/year/
# day/week but not the equally common billing-cycle term "quarter"
# (docs/PROVISIONAL_DECISIONS.md P6.6).
_RATE_QUALIFIER = r"(?:per\s+(?:annum|month|year|day|week|quarter)|p\.a\.|monthly|annually|daily|quarterly)"

# PHASE_6.5: "percent"/"per cent" accepted as word-form alternatives to the
# "%" symbol (Phase 6 found "5 percent" unsupported). Still digit-led only —
# fully spelled-out numbers ("five percent") remain explicitly unsupported,
# same scope decision as currency word-forms (P4.7) — a number-word-to-digit
# converter is a different, larger feature not justified by anything Phase 6
# found.
_PERCENT_UNIT = r"(?:%|percent|per\s+cent)"

_PERCENTAGE_WITH_RATE = re.compile(
    r"(?P<raw>\d+(?:\.\d+)?\s*" + _PERCENT_UNIT + r"\s*" + _RATE_QUALIFIER + r")",
    re.IGNORECASE,
)
_PERCENTAGE_PLAIN = re.compile(r"(?P<raw>\d+(?:\.\d+)?\s*" + _PERCENT_UNIT + r")", re.IGNORECASE)

# ₹ / Rs. / INR and $ currency amounts — other currencies (EUR, GBP, ...)
# and word-form numbers ("five hundred rupees") are explicitly unsupported
# in this phase (Phase 4 spec SS18; docs/PROVISIONAL_DECISIONS.md "Phase 4:
# currency support scope"). The number portion deliberately doesn't assume
# a specific comma-grouping convention (Indian 2-3-digit vs. Western
# 3-digit) — it accepts any digit/comma run so both "1,99,999" and
# "199,999" and an ungrouped "1999.50" all match.
#
# PHASE_6.5 scope decision (docs/PROVISIONAL_DECISIONS.md P6.6): currency
# ranges ("Rs. 1,000 to Rs. 5,000"), percentage ranges ("5-7%"), additional
# currency symbols (EUR/GBP), and word-form numbers remain explicitly
# out of scope — a range needs a genuine schema decision (low/high fields
# on `ExtractedEntity`, or a new entity shape) not justified by anything
# Phase 6 actually found; adding one speculatively risks a silent
# misinterpretation (e.g. treating "5-7%" as two separate 5% and 7% matches).
_NUMBER = r"\d[\d,]*(?:\.\d+)?"
_CURRENCY_AMOUNT = re.compile(
    rf"(?P<raw>(?:₹|Rs\.?|INR|\$)\s?{_NUMBER}|{_NUMBER}\s?(?:₹|Rs\.?|INR|\$))",
    re.IGNORECASE,
)

_TIME_PERIOD = re.compile(
    # Longer alternatives listed first — regex alternation is first-match,
    # not longest-match, so "days" must precede "day" or it would only ever
    # match the "day" prefix and silently drop the trailing "s".
    r"(?P<raw>\d+(?:\.\d+)?\s*(?:days|day|weeks|week|months|month|years|year))",
    re.IGNORECASE,
)

_FEE_KEYWORDS = re.compile(r"\b(fee|charge|penalty|surcharge)\w*\b", re.IGNORECASE)
# How far around a currency amount to look for a fee-indicating word —
# deliberately narrow so unrelated fee mentions elsewhere in a long clause
# don't reclassify an unrelated amount.
_FEE_CONTEXT_WINDOW = 30

_UNIT_WORD = re.compile(r"[a-zA-Z]+")
_CURRENCY_SYMBOL = re.compile(r"₹|Rs\.?|INR|\$", re.IGNORECASE)
# Must start with an actual digit — a bare `[\d,.]+` would let the trailing
# "." in "Rs." itself be mistaken for the start of the number.
_DIGITS = re.compile(r"\d[\d,]*(?:\.\d+)?")

_DETERMINISTIC_CONFIDENCE = 1.0
_CONTEXT_INFERRED_CONFIDENCE = 0.7


@dataclass(frozen=True, slots=True)
class ExtractedEntity:
    entity_type: FinancialEntityType
    value: str
    unit: str | None
    raw_text: str
    # Offsets are relative to the *clause's* raw_text (the only text this
    # service ever sees) — never document-wide (Phase 4 spec SS14).
    start_char: int
    end_char: int
    extraction_confidence: float


def _split_value_unit(raw: str, *, currency: bool) -> tuple[str, str | None]:
    raw = raw.strip()
    if currency:
        symbol_match = _CURRENCY_SYMBOL.search(raw)
        digits_match = _DIGITS.search(raw)
        unit = symbol_match.group(0) if symbol_match else None
        value = digits_match.group(0).replace(",", "") if digits_match else raw
        return value, unit

    digits_match = _DIGITS.search(raw)
    unit_match = _UNIT_WORD.search(raw[digits_match.end() :] if digits_match else raw)
    value = digits_match.group(0) if digits_match else raw
    unit = unit_match.group(0) if unit_match else None
    return value, unit


def _extract_percentages_and_rates(text: str) -> list[ExtractedEntity]:
    entities: list[ExtractedEntity] = []
    consumed_spans: list[tuple[int, int]] = []

    for match in _PERCENTAGE_WITH_RATE.finditer(text):
        raw = match.group("raw")
        percent_part = re.search(r"\d+(?:\.\d+)?", raw)
        value = percent_part.group(0) if percent_part else raw
        entities.append(
            ExtractedEntity(
                entity_type="rate",
                value=value,
                unit="%",
                raw_text=raw,
                start_char=match.start(),
                end_char=match.end(),
                extraction_confidence=_DETERMINISTIC_CONFIDENCE,
            )
        )
        consumed_spans.append((match.start(), match.end()))

    for match in _PERCENTAGE_PLAIN.finditer(text):
        span = (match.start(), match.end())
        if any(span[0] >= s and span[1] <= e for s, e in consumed_spans):
            continue  # already captured as part of a rate match
        raw = match.group("raw")
        percent_part = re.search(r"\d+(?:\.\d+)?", raw)
        value = percent_part.group(0) if percent_part else raw
        entities.append(
            ExtractedEntity(
                entity_type="percentage",
                value=value,
                unit="%",
                raw_text=raw,
                start_char=match.start(),
                end_char=match.end(),
                extraction_confidence=_DETERMINISTIC_CONFIDENCE,
            )
        )

    return entities


def _classify_currency_context(text: str, start: int, end: int) -> tuple[FinancialEntityType, float]:
    window_start = max(0, start - _FEE_CONTEXT_WINDOW)
    window_end = min(len(text), end + _FEE_CONTEXT_WINDOW)
    window = text[window_start:window_end]
    if _FEE_KEYWORDS.search(window):
        return "fee", _CONTEXT_INFERRED_CONFIDENCE
    return "amount", _DETERMINISTIC_CONFIDENCE


def _extract_amounts(text: str) -> list[ExtractedEntity]:
    entities: list[ExtractedEntity] = []
    for match in _CURRENCY_AMOUNT.finditer(text):
        raw = match.group("raw")
        value, unit = _split_value_unit(raw, currency=True)
        entity_type, confidence = _classify_currency_context(text, match.start(), match.end())
        entities.append(
            ExtractedEntity(
                entity_type=entity_type,
                value=value,
                unit=unit,
                raw_text=raw,
                start_char=match.start(),
                end_char=match.end(),
                extraction_confidence=confidence,
            )
        )
    return entities


def _extract_time_periods(text: str) -> list[ExtractedEntity]:
    entities: list[ExtractedEntity] = []
    for match in _TIME_PERIOD.finditer(text):
        raw = match.group("raw")
        value, unit = _split_value_unit(raw, currency=False)
        entities.append(
            ExtractedEntity(
                entity_type="time_period",
                value=value,
                unit=unit,
                raw_text=raw,
                start_char=match.start(),
                end_char=match.end(),
                extraction_confidence=_DETERMINISTIC_CONFIDENCE,
            )
        )
    return entities


def extract_financial_entities(clause_text: str) -> list[ExtractedEntity]:
    """Deterministic, explainable, regex-based extraction — no LLM, no
    financial calculation. Never raises on malformed/unusual input; a
    pattern that doesn't match is simply not extracted.
    """
    entities = [
        *_extract_percentages_and_rates(clause_text),
        *_extract_amounts(clause_text),
        *_extract_time_periods(clause_text),
    ]
    return sorted(entities, key=lambda e: e.start_char)


def persist_entities(
    db: Session, clause_analysis_id: uuid.UUID, entities: list[ExtractedEntity]
) -> list[db_models.FinancialEntity]:
    """Writes extracted entities as `financial_entities` rows (existing
    schema, no new table — Phase 4 spec SS21). Each entity also gets an
    unverified `evidence_spans` row (`verified=False`) carrying its exact
    `raw_text` + offsets, linked via `evidence_span_id` — this is the
    schema's existing mechanism for "preserve source location for Phase 5"
    (Phase 4 spec SS14); the Evidence Engine (Phase 5) verifies and flips
    `verified=True`, it is never created pre-verified here.
    """
    rows: list[db_models.FinancialEntity] = []
    for entity in entities:
        span = db_models.EvidenceSpan(
            id=uuid.uuid4(),
            clause_analysis_id=clause_analysis_id,
            text=entity.raw_text,
            start_char=entity.start_char,
            end_char=entity.end_char,
            verified=False,
        )
        db.add(span)
        row = db_models.FinancialEntity(
            id=uuid.uuid4(),
            clause_analysis_id=clause_analysis_id,
            entity_type=entity.entity_type,
            value=entity.value,
            unit=entity.unit,
            raw_text=entity.raw_text,
            evidence_span_id=span.id,
        )
        db.add(row)
        rows.append(row)

    db.flush()
    return rows
