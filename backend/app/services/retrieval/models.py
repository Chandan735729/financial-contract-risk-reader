"""Internal hybrid-retrieval contract — AI_Risk_Engine_Design.md SS2, Phase 4
spec SS2-SS7.

Not the `matched_patterns` DB row and not the public `MatchedPattern`
Pydantic model directly — this is the in-memory shape
`retrieval_service.py` builds before persisting. Mirrors the pattern
established by `app/services/parsing/models.py` and
`app/services/segmentation_models.py`.

`similarity_score` (dense) and `lexical_score` are always kept on the same
`PatternMatch` record but never combined into one number here (Phase 4 spec
SS3) — that combination is explicitly the Risk Engine's job (Phase 5).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class PatternMatch:
    corpus_pattern_id: uuid.UUID
    similarity_score: float  # dense, cosine similarity in [0, 1] (post-normalization; can be negative in theory, clamped at query time)
    lexical_score: float  # BM25-derived, normalized to [0, 1]
    risk_category: str | None
    risk_subcategory: str | None
    is_negative_example: bool
    source: str | None
    taxonomy_version: str
    corpus_version: str
    # Which retrieval method(s) actually placed this pattern in the
    # top-k candidate set — a pattern found by only one method still gets
    # both scores computed (never a fabricated 0.0 for the other), but this
    # records which method(s) considered it "relevant enough to surface"
    # (diagnostic only; not persisted).
    found_by_dense: bool
    found_by_lexical: bool


@dataclass(frozen=True, slots=True)
class RetrievalResult:
    """Outcome of retrieval for one clause. `matches == ()` is the explicit
    "no signal" state (Phase 4 spec SS6) — distinguishable from "safe" by
    construction: nothing downstream may treat an empty `matches` tuple as
    evidence of low risk, only as absence of a retrieval signal.
    """

    matches: tuple[PatternMatch, ...] = field(default_factory=tuple)
    taxonomy_version: str = ""
    corpus_version: str = ""
    document_type_filter_applied: bool = False
    # Non-empty only when retrieval could not proceed as requested (e.g. no
    # corpus patterns exist at all, or none match the expected
    # taxonomy/corpus version) — distinct from "ran fine, found nothing
    # above the floor".
    diagnostic: str | None = None

    @property
    def has_signal(self) -> bool:
        return len(self.matches) > 0
