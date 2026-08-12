"""Evidence Engine — Grounding_and_Evidence_Spec.md SS2, Phase 5 spec SS1-4.

Assembles candidate evidence spans for each signal contributing to a
clause's risk score (extracted entities, extracted condition text,
deterministic rule hits) and mechanically verifies every one against the
clause's own `raw_text` before it is ever treated as "evidence."

**Verification is non-negotiable** (Phase 5 spec SS2): a candidate span is
checked either (a) at its claimed offsets, allowing only whitespace/
punctuation normalization, or (b) by locating its exact text within
`raw_text` when no offsets are claimed yet (condition-extracted text, which
Phase 4 stores as a string, not an offset — see
docs/PROVISIONAL_DECISIONS.md "Phase 4: condition extraction does not
create evidence_spans rows"). A span that fails either path is discarded —
never displayed, never counted as verified, never silently relocated or
"repaired" (Phase 5 spec SS2: "Do not silently repair a fabricated span.
Record a diagnostic condition instead.").

**Retrieval/lexical corpus matches deliberately produce no evidence spans
here** — a `corpus_pattern.pattern_text` is not clause text, so there is no
honest clause-text span to point to for a bare retrieval match
(PROVISIONAL_V2; see docs/PROVISIONAL_DECISIONS.md "Phase 5: retrieval/
lexical signals do not produce evidence spans"). Only `entity`, `condition`,
and `rule` sourced candidates are assembled/verified here; retrieval/lexical
still feed `risk_engine.py`'s score and confidence numerically, they just
never satisfy the HIGH/MEDIUM verified-evidence gate on their own — this is
the concrete mechanism that keeps "high similarity" from silently becoming
"verified evidence" (Phase 5 spec SS10, test case D).
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal

from sqlalchemy.orm import Session

from app.models import db_models

EvidenceSource = Literal["entity", "condition", "rule"]

_WHITESPACE_RE = re.compile(r"\s+")
_PUNCT_NORMALIZE: dict[str, str] = {
    "‘": "'",
    "’": "'",
    "“": '"',
    "”": '"',
    "–": "-",
    "—": "-",
}


def _normalize(text: str) -> str:
    """Whitespace/punctuation normalization only (Grounding_and_Evidence_Spec.md
    SS2: "allowing minor whitespace/punctuation normalization") — never a
    fuzzy/substring match. Case is deliberately left untouched: a case
    mismatch between claimed and actual text is a genuine fabrication signal,
    not formatting noise.
    """
    for original, replacement in _PUNCT_NORMALIZE.items():
        text = text.replace(original, replacement)
    return _WHITESPACE_RE.sub(" ", text.strip())


def verify_span(raw_text: str, text: str, start_char: int, end_char: int) -> bool:
    """The core mechanical check (Grounding_and_Evidence_Spec.md SS2). Public
    so it is directly unit-testable per Phase 5 spec SS22's test list
    without needing to build a full `EvidenceCandidate`.
    """
    if not text or not text.strip():
        return False
    if start_char < 0 or end_char < start_char or end_char > len(raw_text):
        return False
    actual = raw_text[start_char:end_char]
    return actual == text or _normalize(actual) == _normalize(text)


def _locate(raw_text: str, text: str) -> tuple[int, int] | None:
    """Finds `text` inside `raw_text` when no offsets are claimed yet. Exact
    substring search first (condition-extracted text is documented to already
    be an exact substring — see module docstring); a whitespace-normalized
    fallback handles minor internal spacing differences only. Case-sensitive
    throughout — never a fuzzy match that could locate an unrelated phrase.
    """
    if not text or not text.strip():
        return None
    idx = raw_text.find(text)
    if idx != -1:
        return idx, idx + len(text)

    tokens = text.split()
    if not tokens:
        return None
    pattern = re.compile(r"\s+".join(re.escape(token) for token in tokens))
    match = pattern.search(raw_text)
    if match is None:
        return None
    return match.start(), match.end()


@dataclass(frozen=True, slots=True)
class EvidenceCandidate:
    source: EvidenceSource
    text: str
    # `None` when the candidate has no claimed offset yet (condition text) —
    # `_verify_candidate` locates it instead of checking a claim.
    start_char: int | None
    end_char: int | None
    page_number: int | None


@dataclass(frozen=True, slots=True)
class VerifiedEvidence:
    source: EvidenceSource
    text: str
    start_char: int
    end_char: int
    page_number: int | None
    verified: bool = True


@dataclass(frozen=True, slots=True)
class EvidenceResult:
    """`verified` is the only evidence ever eligible for display or for the
    HIGH/MEDIUM gate (Phase 5 spec SS17). `unverifiable_count`/`diagnostics`
    exist purely for internal error-analysis (Dataset_and_Evaluation_Spec.md
    SS7 `evidence_extraction_error`) — never shown to a user, never treated
    as evidence.
    """

    verified: tuple[VerifiedEvidence, ...]
    unverifiable_count: int
    diagnostics: tuple[str, ...]


def _verify_candidate(raw_text: str, candidate: EvidenceCandidate) -> VerifiedEvidence | None:
    if candidate.start_char is not None and candidate.end_char is not None:
        if not verify_span(raw_text, candidate.text, candidate.start_char, candidate.end_char):
            return None
        return VerifiedEvidence(
            source=candidate.source,
            text=candidate.text,
            start_char=candidate.start_char,
            end_char=candidate.end_char,
            page_number=candidate.page_number,
        )

    located = _locate(raw_text, candidate.text)
    if located is None:
        return None
    start, end = located
    return VerifiedEvidence(
        source=candidate.source,
        text=raw_text[start:end],
        start_char=start,
        end_char=end,
        page_number=candidate.page_number,
    )


def assemble_and_verify_evidence(
    clause_raw_text: str,
    *,
    page_number: int | None,
    entities: Sequence[Any],
    trigger: str | None,
    condition_text: str | None,
    consequence: str | None,
    rule_matches: Sequence[Any],
) -> EvidenceResult:
    """Builds every candidate span this clause's already-collected Phase 4/5
    signals support, then verifies each one against `clause_raw_text`.

    `entities` items need only `raw_text`, `start_char`, `end_char`
    attributes (Phase 4's `ExtractedEntity` or the `EntitySignal` adapter in
    `risk_engine.py` both satisfy this). `rule_matches` items need
    `evidence_text`, `start_char`, `end_char` (`risk_rules.RuleMatch`).
    """
    candidates: list[EvidenceCandidate] = []
    for entity in entities:
        candidates.append(
            EvidenceCandidate(
                source="entity",
                text=entity.raw_text,
                start_char=entity.start_char,
                end_char=entity.end_char,
                page_number=page_number,
            )
        )
    for field_text in (trigger, condition_text, consequence):
        if field_text:
            candidates.append(
                EvidenceCandidate(
                    source="condition",
                    text=field_text,
                    start_char=None,
                    end_char=None,
                    page_number=page_number,
                )
            )
    for rule_match in rule_matches:
        candidates.append(
            EvidenceCandidate(
                source="rule",
                text=rule_match.evidence_text,
                start_char=rule_match.start_char,
                end_char=rule_match.end_char,
                page_number=page_number,
            )
        )

    verified: list[VerifiedEvidence] = []
    seen: set[tuple[int, int, str]] = set()
    diagnostics: list[str] = []
    unverifiable = 0

    for candidate in candidates:
        result = _verify_candidate(clause_raw_text, candidate)
        if result is None:
            unverifiable += 1
            diagnostics.append(f"unverifiable evidence candidate from source={candidate.source}")
            continue
        key = (result.start_char, result.end_char, result.text)
        if key in seen:
            continue  # exact duplicate (e.g. the same phrase found by two sources) — not a new span
        seen.add(key)
        verified.append(result)

    return EvidenceResult(
        verified=tuple(verified), unverifiable_count=unverifiable, diagnostics=tuple(diagnostics)
    )


def persist_evidence(
    db: Session, clause_analysis: db_models.ClauseAnalysisORM, result: EvidenceResult
) -> list[db_models.EvidenceSpan]:
    """Writes verified evidence to the existing `evidence_spans` table (no
    new table — Phase 5 spec SS18). Entity-sourced evidence already has an
    unverified row from Phase 4 (`entity_extraction_service.persist_entities`)
    linked via `financial_entities.evidence_span_id` — this flips that row's
    `verified` flag in place rather than creating a duplicate. Condition- and
    rule-sourced evidence have no prior row, so a new one is created.
    """
    existing_by_offset = {(span.start_char, span.end_char): span for span in clause_analysis.evidence_spans}
    new_rows: list[db_models.EvidenceSpan] = []

    for item in result.verified:
        existing = existing_by_offset.get((item.start_char, item.end_char))
        if existing is not None and item.source == "entity":
            existing.verified = True
            continue
        row = db_models.EvidenceSpan(
            id=uuid.uuid4(),
            clause_analysis_id=clause_analysis.id,
            text=item.text,
            start_char=item.start_char,
            end_char=item.end_char,
            page_number=item.page_number,
            verified=True,
        )
        db.add(row)
        new_rows.append(row)

    db.flush()
    return new_rows
