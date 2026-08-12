"""Clause segmentation — Technical_Architecture_v2.md SS3 (Segmentation
Service): "heuristic rule-based, per clause: text + position."

Deliberately rule/layout-based, not LLM-based (Phase 3 spec, "IMPORTANT
DESIGN RULE") — segmentation decisions come from numbering patterns,
heading/style signals, and reading order, all of which are explainable and
reproducible. An ML/LLM-assisted enhancement is an explicit future upgrade,
not implemented here.

Pipeline (module layout mirrors this order):
    ParsedDocument (Phase 2)
        -> structure analysis (`_classify_block`)
        -> repeated header/footer suppression (`_detect_repeated_lines`)
        -> boundary detection + clause assembly (`_assemble_clauses`)
        -> heuristic confidence scoring (`_score_clause`, `_detect_document_anomaly`)
        -> `segment_document()` ties the above together
        -> `persist_clauses()` writes the result as `Clause` rows

Confidence here is **heuristic segmentation confidence** — "how confident
are we this text was split correctly" — a completely different axis from
the Risk Engine's (future) calibrated `confidence_score` on `ClauseAnalysis`
(PRD_v2.md Product Principle 4/9). It is not calibrated against a labeled
benchmark; see `docs/PROVISIONAL_DECISIONS.md` "Phase 3: heuristic
segmentation confidence, not calibrated" and `segmentation_metrics.py` for
the measured evaluation this heuristic is checked against.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from typing import Literal

from sqlalchemy.orm import Session

from app.core.logging import get_logger, log_event
from app.models import db_models
from app.models.enums import ErrorCode
from app.services.parsing.models import DocumentTextBlock, ParsedDocument
from app.services.segmentation_models import SegmentationDiagnostics, SegmentationResult, SegmentedClause

logger = get_logger(__name__)

# ==================================================================
# 1. Structure analysis — numbering / heading signal detection
# ==================================================================

BoundarySignal = Literal[
    "top_numeric",
    "sub_numeric",
    "lettered",
    "roman",
    "section_word",
    "heading_like",
    "after_heading",
    "fallback",
]

# Multi-level numeric: "3.1 ", "1.1.1. " — requires >=1 dot-separated
# sub-component beyond the first number, so it never matches a bare "1. ".
_NUMERIC_MULTI = re.compile(r"^\s*(\d+(?:\.\d+){1,4})\.?\s+\S")
# Bare top-level numeric: "1. ", "23. "
_NUMERIC_TOP = re.compile(r"^\s*(\d{1,3})\.\s+\S")
# "(a) " / "(iv) " — captured together, disambiguated by length/charset below.
_BRACKETED = re.compile(r"^\s*\(([a-zA-Z]{1,6})\)\s+\S")
_ROMAN_CHARS = set("ivxlcdm")
_SECTION_WORD = re.compile(r"^\s*(?:Section|Clause|Article)\s+(\d+(?:\.\d+)*)\b", re.IGNORECASE)

# A short, unpunctuated line is a plausible heading even without an explicit
# style signal (PDF has no style metadata) — kept intentionally conservative
# (Phase 3 spec SS2: "signals must be combined", never numbering/length alone).
_HEADING_MAX_CHARS = 80
_TRAILING_SENTENCE_PUNCTUATION = (".", ";", ",", ":")


@dataclass(frozen=True, slots=True)
class _BlockSignal:
    numbering_kind: BoundarySignal | None
    numbering_value: str | None
    is_heading_like: bool  # any heading evidence, DOCX-style or bold-heuristic
    is_explicit_heading: bool  # DOCX style-based only — safe to exclude from raw_text


def _classify_bracketed(token: str) -> BoundarySignal:
    if len(token) >= 2 and set(token.lower()) <= _ROMAN_CHARS:
        return "roman"
    return "lettered"


def _looks_like_heading_text(text: str) -> bool:
    stripped = text.strip()
    if not stripped or len(stripped) > _HEADING_MAX_CHARS:
        return False
    if stripped.endswith(_TRAILING_SENTENCE_PUNCTUATION):
        return False
    # A heading is short and title-like; a long run-on without punctuation
    # is more likely a truncated sentence than a title, so require a modest
    # word-count ceiling too.
    return len(stripped.split()) <= 12


def _classify_block(block: DocumentTextBlock) -> _BlockSignal:
    text = block.text
    numbering_kind: BoundarySignal | None = None
    numbering_value: str | None = None

    if m := _NUMERIC_MULTI.match(text):
        numbering_kind, numbering_value = "sub_numeric", m.group(1)
    elif m := _NUMERIC_TOP.match(text):
        numbering_kind, numbering_value = "top_numeric", m.group(1)
    elif m := _BRACKETED.match(text):
        numbering_kind, numbering_value = _classify_bracketed(m.group(1)), m.group(1)
    elif m := _SECTION_WORD.match(text):
        numbering_kind, numbering_value = "section_word", m.group(1)

    is_explicit_heading = block.is_heading and not block.is_table_cell
    is_bold_heading_like = (
        not block.is_table_cell
        and block.is_bold
        and not block.is_list_item
        and _looks_like_heading_text(text)
    )
    is_heading_like = is_explicit_heading or is_bold_heading_like

    return _BlockSignal(
        numbering_kind=numbering_kind,
        numbering_value=numbering_value,
        is_heading_like=is_heading_like,
        is_explicit_heading=is_explicit_heading,
    )


# ==================================================================
# 2. Repeated header/footer suppression
# ==================================================================

_PAGE_NUMBER_LINE = re.compile(r"^\s*(page\s+)?\d{1,4}(\s+of\s+\d{1,4})?\s*$", re.IGNORECASE)
_DIGIT_RUN = re.compile(r"\d+")
# A running header/footer must repeat on at least this many distinct pages
# to be suppressed — chosen so a 2-page document's genuinely repeated title
# isn't mistaken for a footer, while a 3+ page repeated line reliably is one.
_MIN_REPEAT_PAGES = 3
# Only lines this short are even *candidates* for repetition-based
# suppression — real header/footer lines are brief. This deliberately
# excludes normal clause-length sentences from ever being compared by
# digit-normalized text, so two different sentences that merely happen to
# each contain a different number (e.g. two filler paragraphs) are never
# mistaken for a repeated footer that varies only by page number.
_HEADER_FOOTER_CANDIDATE_MAX_CHARS = 60


def _normalize_for_repetition(text: str) -> str:
    return _DIGIT_RUN.sub("#", " ".join(text.strip().lower().split()))


def _detect_repeated_lines(blocks: tuple[DocumentTextBlock, ...]) -> frozenset[int]:
    """Returns the `id()`s of blocks to exclude from clause content as
    probable running headers/footers (Phase 3 spec SS5).

    Two independent signals, either sufficient alone:
      1. A lone page-number-shaped line ("Page 3 of 12", "7") — safe even in
         a single-page document, since the pattern alone is diagnostic.
      2. A short (<= `_HEADER_FOOTER_CANDIDATE_MAX_CHARS`) line whose
         normalized (whitespace/case/digit-collapsed) text repeats on
         >= `_MIN_REPEAT_PAGES` distinct pages.
    """
    suppressed: set[int] = set()
    pages_by_norm: dict[str, set[int]] = {}
    blocks_by_norm: dict[str, list[DocumentTextBlock]] = {}

    for block in blocks:
        stripped = block.text.strip()
        if _PAGE_NUMBER_LINE.match(stripped):
            suppressed.add(id(block))
            continue
        if not stripped or len(stripped) > _HEADER_FOOTER_CANDIDATE_MAX_CHARS:
            continue
        norm = _normalize_for_repetition(stripped)
        pages_by_norm.setdefault(norm, set()).add(block.page_number or 0)
        blocks_by_norm.setdefault(norm, []).append(block)

    for norm, pages in pages_by_norm.items():
        if len(pages) >= _MIN_REPEAT_PAGES:
            suppressed.update(id(b) for b in blocks_by_norm[norm])

    return frozenset(suppressed)


# ==================================================================
# 3. Boundary detection + clause assembly
# ==================================================================

_RAW_TEXT_JOIN = "\n"


@dataclass
class _ClauseGroup:
    blocks: list[DocumentTextBlock]
    section_heading: str | None
    boundary_signal: BoundarySignal


def _assemble_groups(
    blocks: tuple[DocumentTextBlock, ...], suppressed_ids: frozenset[int]
) -> tuple[list[_ClauseGroup], SegmentationDiagnostics]:
    groups: list[_ClauseGroup] = []
    current: _ClauseGroup | None = None
    current_heading: str | None = None
    # True only for the content immediately following a freshly-set explicit
    # heading, with no clause opened yet under it — a heading is strong
    # evidence a new clause starts right after it, even without its own
    # numbering, so that first block earns a stronger signal than generic
    # unstructured "fallback" prose (Phase 3 spec SS2: combine signals).
    just_saw_heading = False

    total_chars = sum(len(b.text) for b in blocks)
    suppressed_chars = sum(len(b.text) for b in blocks if id(b) in suppressed_ids)
    heading_block_count = 0
    heading_metadata_chars = 0

    for block in blocks:
        if id(block) in suppressed_ids:
            continue

        signal = _classify_block(block)

        if signal.is_explicit_heading:
            if current is not None:
                groups.append(current)
                current = None
            current_heading = block.text.strip()
            heading_block_count += 1
            heading_metadata_chars += len(block.text)
            just_saw_heading = True
            continue

        starts_new_clause = signal.numbering_kind is not None or signal.is_heading_like
        if starts_new_clause:
            if current is not None:
                groups.append(current)
            boundary_signal: BoundarySignal = signal.numbering_kind or "heading_like"
            current = _ClauseGroup(
                blocks=[block], section_heading=current_heading, boundary_signal=boundary_signal
            )
            just_saw_heading = False
            continue

        # Continuation, or the first content the document has seen at all.
        if current is None:
            fallback_signal: BoundarySignal = "after_heading" if just_saw_heading else "fallback"
            current = _ClauseGroup(
                blocks=[block], section_heading=current_heading, boundary_signal=fallback_signal
            )
            just_saw_heading = False
        else:
            current.blocks.append(block)

    if current is not None:
        groups.append(current)

    covered_chars = sum(len(b.text) for g in groups for b in g.blocks)
    diagnostics = SegmentationDiagnostics(
        total_blocks=len(blocks),
        suppressed_block_count=sum(1 for b in blocks if id(b) in suppressed_ids),
        heading_block_count=heading_block_count,
        total_chars=total_chars,
        suppressed_chars=suppressed_chars,
        heading_metadata_chars=heading_metadata_chars,
        covered_chars=covered_chars,
    )
    return groups, diagnostics


# ==================================================================
# 4. Heuristic confidence scoring
# ==================================================================

_BASE_CONFIDENCE: dict[BoundarySignal, float] = {
    "top_numeric": 0.90,
    "sub_numeric": 0.88,
    "lettered": 0.85,
    "roman": 0.85,
    "section_word": 0.82,
    "heading_like": 0.80,
    "after_heading": 0.75,
    "fallback": 0.55,
}
_LARGE_CLAUSE_CHARS = 4000
_VERY_LARGE_CLAUSE_CHARS = 8000
_TINY_CLAUSE_CHARS = 20
_FRAGMENTATION_MIN_BLOCKS = 8
_FRAGMENTATION_MAX_AVG_CHARS = 20.0
_LOW_CONFIDENCE_THRESHOLD = 0.6


def _score_clause(group: _ClauseGroup, raw_text: str) -> float:
    score = _BASE_CONFIDENCE[group.boundary_signal]
    char_len = len(raw_text)
    block_count = len(group.blocks)

    if char_len >= _VERY_LARGE_CLAUSE_CHARS:
        score -= 0.35
    elif char_len >= _LARGE_CLAUSE_CHARS:
        score -= 0.15

    if char_len < _TINY_CLAUSE_CHARS:
        score -= 0.25

    if block_count >= _FRAGMENTATION_MIN_BLOCKS and (char_len / block_count) < _FRAGMENTATION_MAX_AVG_CHARS:
        score -= 0.20

    return max(0.05, min(0.99, score))


def _detect_document_anomaly(groups: list[_ClauseGroup], diagnostics: SegmentationDiagnostics) -> str | None:
    """Whole-document quality signals (Phase 3 spec SS9) — when present,
    every clause in the document is flagged low-confidence, since the
    problem is structural, not isolated to one clause."""
    if not groups:
        return "no_clauses_produced"

    total_covered = diagnostics.covered_chars
    if total_covered > 0:
        largest = max(sum(len(b.text) for b in g.blocks) for g in groups)
        if len(groups) > 1 and largest / total_covered > 0.85:
            return "single_clause_dominates_document"

    if len(groups) >= 20:
        avg_size = total_covered / len(groups) if groups else 0
        fallback_ratio = sum(1 for g in groups if g.boundary_signal == "fallback") / len(groups)
        if avg_size < 40 and fallback_ratio > 0.5:
            return "many_tiny_fragments"

    top_numeric_sequence: list[int] = []
    for g in groups:
        if g.boundary_signal != "top_numeric":
            continue
        numbering_value = _classify_block(g.blocks[0]).numbering_value
        if numbering_value is not None:
            top_numeric_sequence.append(int(numbering_value))
    if len(top_numeric_sequence) >= 3:
        # Well-formed sequential numbering never goes backward — even one
        # decrease (e.g. "9." followed later by "3.") is a strong signal of
        # either a genuine drafting irregularity or a numbering
        # misclassification, either way worth surfacing as low-confidence.
        decreases = sum(
            1 for a, b in zip(top_numeric_sequence, top_numeric_sequence[1:], strict=False) if b < a
        )
        if decreases >= 1:
            return "inconsistent_numbering"

    return None


# ==================================================================
# 5. Entry point
# ==================================================================


def segment_document(parsed: ParsedDocument) -> SegmentationResult:
    """Rule/layout-based segmentation (Technical_Architecture_v2.md SS3).
    Never raises on malformed/empty input — an empty `ParsedDocument`
    produces a zero-clause result with `low_confidence_flag=True`, not an
    exception (Phase 3 spec SS13 "empty/invalid parser result").
    """
    if not parsed.blocks:
        diagnostics = SegmentationDiagnostics(
            total_blocks=0,
            suppressed_block_count=0,
            heading_block_count=0,
            total_chars=0,
            suppressed_chars=0,
            heading_metadata_chars=0,
            covered_chars=0,
            document_level_anomaly="no_text_blocks",
        )
        return SegmentationResult(clauses=(), low_confidence_flag=True, diagnostics=diagnostics)

    suppressed_ids = _detect_repeated_lines(parsed.blocks)
    groups, diagnostics = _assemble_groups(parsed.blocks, suppressed_ids)
    anomaly = _detect_document_anomaly(groups, diagnostics)
    diagnostics = SegmentationDiagnostics(
        total_blocks=diagnostics.total_blocks,
        suppressed_block_count=diagnostics.suppressed_block_count,
        heading_block_count=diagnostics.heading_block_count,
        total_chars=diagnostics.total_chars,
        suppressed_chars=diagnostics.suppressed_chars,
        heading_metadata_chars=diagnostics.heading_metadata_chars,
        covered_chars=diagnostics.covered_chars,
        document_level_anomaly=anomaly,
    )
    document_low_confidence = anomaly is not None

    clauses: list[SegmentedClause] = []
    for index, group in enumerate(groups):
        raw_text = _RAW_TEXT_JOIN.join(b.text for b in group.blocks)
        confidence = _score_clause(group, raw_text)
        low_confidence = document_low_confidence or confidence < _LOW_CONFIDENCE_THRESHOLD
        first_block, last_block = group.blocks[0], group.blocks[-1]
        clauses.append(
            SegmentedClause(
                clause_index=index,
                raw_text=raw_text,
                section_heading=group.section_heading,
                page_number=first_block.page_number,
                start_char=first_block.start_char,
                end_char=last_block.end_char,
                segmentation_confidence=confidence,
                low_confidence_flag=low_confidence,
                boundary_signal=group.boundary_signal,
                block_count=len(group.blocks),
                start_block_order=first_block.order,
            )
        )

    return SegmentationResult(
        clauses=tuple(clauses), low_confidence_flag=document_low_confidence, diagnostics=diagnostics
    )


# ==================================================================
# 6. Persistence
# ==================================================================


def persist_clauses(
    db: Session, document_id: uuid.UUID, result: SegmentationResult
) -> list[db_models.Clause]:
    """Writes `result.clauses` as `Clause` rows and advances the document's
    `ProcessingJob` stage. Uses `flush()`, not `commit()` — matching the
    Phase 2 upload endpoint's transaction pattern (Phase 3 spec SS16: never
    leave a partially written clause set; the caller's `Depends(get_db)`
    performs the final commit, so a flush failure here still rolls back the
    whole batch, not just the failing row).

    Raises whatever SQLAlchemy raises on a flush failure — callers must not
    swallow it silently (that would leave the processing job stuck at
    SEGMENTING with no record of failure).
    """
    rows: list[db_models.Clause] = []
    for clause in result.clauses:
        row = db_models.Clause(
            id=uuid.uuid4(),
            document_id=document_id,
            clause_index=clause.clause_index,
            section_heading=clause.section_heading,
            raw_text=clause.raw_text,
            start_char=clause.start_char,
            end_char=clause.end_char,
            page_number=clause.page_number,
            segmentation_confidence=clause.segmentation_confidence,
            low_confidence_flag=clause.low_confidence_flag,
        )
        db.add(row)
        rows.append(row)

    job = db.query(db_models.ProcessingJob).filter_by(document_id=document_id).one_or_none()
    if job is not None:
        if result.clauses:
            job.stage = db_models.ProcessingStage.UNDERSTANDING
            job.error_code = None
        else:
            job.stage = db_models.ProcessingStage.FAILED
            job.error_code = ErrorCode.SEGMENTATION_LOW_CONFIDENCE.value

    db.flush()

    # Safe metadata only — never raw_text, section_heading content, or any
    # other clause text (Security_and_Privacy_v2.md SS6; ALLOWED_LOG_FIELDS
    # is the enforced allowlist, not this call site's judgment call).
    log_event(
        logger,
        "clauses_persisted",
        document_id=str(document_id),
        stage=(job.stage.value if job is not None else None),
        count=len(rows),
        low_confidence_flag=result.low_confidence_flag,
    )
    return rows


# ==================================================================
# 7. Text-preservation invariants (Phase 3 spec SS10)
# ==================================================================


def validate_invariants(parsed: ParsedDocument, result: SegmentationResult) -> list[str]:
    """Returns a list of violated-invariant descriptions; empty means every
    invariant held. Exact character-level `raw_text` reconstruction against
    the original document is *not* one of these invariants — see
    `SegmentedClause`'s docstring on `start_char`/`end_char` semantics for
    why that's not guaranteed, and what is checked instead.
    """
    violations: list[str] = []
    clauses = result.clauses

    if [c.clause_index for c in clauses] != list(range(len(clauses))):
        violations.append("clause_index is not sequential starting at 0")

    orders = [c.start_block_order for c in clauses]
    if orders != sorted(orders):
        violations.append(
            "clauses do not preserve document reading order (start_block_order not non-decreasing)"
        )

    for c in clauses:
        if not c.raw_text.strip():
            violations.append(f"clause {c.clause_index} has empty raw_text")

    if result.diagnostics is not None:
        d = result.diagnostics
        accounted = d.covered_chars + d.suppressed_chars + d.heading_metadata_chars
        if accounted != d.total_chars:
            violations.append(
                f"char accounting mismatch: covered({d.covered_chars}) + suppressed({d.suppressed_chars}) + "
                f"heading({d.heading_metadata_chars}) = {accounted} != total_chars({d.total_chars}) "
                "(implies lost, duplicated, or overlapping text)"
            )

    valid_page_numbers = {b.page_number for b in parsed.blocks if b.page_number is not None}
    for c in clauses:
        if c.page_number is not None and c.page_number not in valid_page_numbers:
            violations.append(f"clause {c.clause_index} page_number {c.page_number} does not exist in source")

    valid_start_offsets = {b.start_char for b in parsed.blocks if b.start_char is not None}
    valid_end_offsets = {b.end_char for b in parsed.blocks if b.end_char is not None}
    for c in clauses:
        if c.start_char is not None and c.start_char not in valid_start_offsets:
            violations.append(
                f"clause {c.clause_index} start_char {c.start_char} not traceable to a source block"
            )
        if c.end_char is not None and c.end_char not in valid_end_offsets:
            violations.append(
                f"clause {c.clause_index} end_char {c.end_char} not traceable to a source block"
            )
        if c.start_char is not None and c.end_char is not None and c.start_char > c.end_char:
            violations.append(f"clause {c.clause_index} has start_char > end_char")

    return violations
