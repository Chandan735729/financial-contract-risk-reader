"""Internal segmentation contract — Technical_Architecture_v2.md SS3
(Segmentation Service): "Text blocks -> discrete clauses. Outputs
`Clause[]` with `clause_index`, `raw_text`, `section_heading`, position."

Not Pydantic/API models and not the SQLAlchemy `Clause` row directly: this
is the in-memory representation `segmentation_service.py` builds before
persisting (`persist_clauses`). Mirrors the shape of
`app/services/parsing/models.py` (Phase 2's equivalent internal contract).

Frozen dataclasses on purpose — this contract never crosses a process/API
boundary and is never serialized.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class SegmentedClause:
    """One assembled clause, ready to persist as a `Clause` row.

    `start_char`/`end_char` reference the *source* `DocumentTextBlock`
    offsets from Phase 2's `ParsedDocument` (the first and last contributing
    block's own offsets) — not a byte-exact slice bound of `raw_text`, since
    `raw_text` is built by joining block texts with a separator that isn't
    present in the original offset space, and heading/suppressed blocks in
    between are excluded from `raw_text` but not from the offset range they
    fall within. See docs/PROVISIONAL_DECISIONS.md "Phase 3: start_char/
    end_char semantics" — this is a documented, not a claimed-exact,
    invariant (Phase 3 spec SS10).
    """

    clause_index: int
    raw_text: str
    section_heading: str | None
    page_number: int | None
    start_char: int | None
    end_char: int | None
    segmentation_confidence: float
    low_confidence_flag: bool
    # Diagnostics only — never persisted, never exposed publicly (Phase 3
    # spec SS17: "Do not expose internal structure-analysis signals
    # unnecessarily").
    boundary_signal: str
    block_count: int
    # `DocumentTextBlock.order` of the first contributing block — the
    # "boundary position" the evaluation harness compares against ground
    # truth (segmentation_metrics.py).
    start_block_order: int


@dataclass(frozen=True, slots=True)
class SegmentationDiagnostics:
    """Document-level accounting — used for confidence decisions and the
    evaluation harness's diagnostic report (Phase 3 spec SS12). Never
    contains raw clause/block text (Security_and_Privacy_v2.md SS6)."""

    total_blocks: int
    suppressed_block_count: int
    heading_block_count: int
    total_chars: int
    suppressed_chars: int
    heading_metadata_chars: int
    covered_chars: int
    document_level_anomaly: str | None = None


@dataclass(frozen=True, slots=True)
class SegmentationResult:
    clauses: tuple[SegmentedClause, ...] = field(default_factory=tuple)
    low_confidence_flag: bool = False
    diagnostics: SegmentationDiagnostics | None = None
