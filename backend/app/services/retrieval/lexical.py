"""Lexical retrieval — AI_Risk_Engine_Design.md SS2 ("keyword/BM25-style
match against corpus pattern text"), Phase 4 spec SS2.

Deterministic, explainable, no external dependency beyond `rank_bm25` (a
small pure-Python package — Phase 4 spec SS2 "Do not over-engineer this").
Built fresh per retrieval batch from whatever corpus patterns are passed in
(cheap at the "hundreds to low thousands" corpus scale this MVP targets —
Technical_Architecture_v2.md SS9); no persistent lexical index is
maintained, unlike the vector store.

**Normalization:** raw BM25 scores are unbounded and their scale depends on
corpus statistics (term frequencies/IDF), so they're mapped into `[0, 1)`
via a saturating transform `score / (score + K)`, *not* min-max normalized
against the query's own candidate set. Min-max normalization was tried
first and rejected: on a small candidate set, whichever pattern scores
highest gets pushed to exactly 1.0 regardless of whether it's actually
relevant — on a 5-pattern test corpus a completely unrelated query still
produced a 1.0 "top" lexical score purely from BM25's IDF noise. The
saturating transform instead reports a low score for a low raw score
regardless of what else is in the candidate set. See
docs/PROVISIONAL_DECISIONS.md "Phase 4: lexical score normalization" — `K`
is a documented heuristic constant, not a calibrated value.
"""

from __future__ import annotations

import re

from rank_bm25 import BM25Okapi

_TOKEN = re.compile(r"[a-zA-Z0-9']+")

# Chosen so a strong/near-exact textual match (raw BM25 score in the
# high single digits to tens, observed empirically for real overlap on
# corpus-scale text) saturates toward 1.0, while the low-single-digit raw
# scores BM25 produces from incidental token overlap on unrelated text stay
# well below typical floor thresholds (see min_lexical_floor in Settings).
_SATURATION_K = 4.0


def tokenize(text: str) -> list[str]:
    return [t.lower() for t in _TOKEN.findall(text)]


def _saturate(raw_score: float) -> float:
    if raw_score <= 0.0:
        return 0.0
    return raw_score / (raw_score + _SATURATION_K)


class LexicalIndex:
    """BM25 index over a fixed set of (pattern_id, text) pairs. Rebuilt per
    query batch rather than incrementally maintained — see module docstring."""

    def __init__(self, pattern_ids: list[str], texts: list[str]) -> None:
        if len(pattern_ids) != len(texts):
            raise ValueError("pattern_ids and texts must be the same length")
        self._pattern_ids = pattern_ids
        self._corpus_tokens = [tokenize(t) for t in texts]
        self._bm25 = BM25Okapi(self._corpus_tokens) if texts else None

    def __len__(self) -> int:
        return len(self._pattern_ids)

    def query(self, text: str, top_k: int) -> list[tuple[str, float]]:
        """Returns `(pattern_id, normalized_score)` pairs, best first, each
        in `[0, 1)` via the saturating transform (see module docstring) —
        never mixed arithmetically with `similarity_score` (Phase 4 spec SS3)."""
        if self._bm25 is None or not self._pattern_ids:
            return []

        raw_scores = self._bm25.get_scores(tokenize(text))
        scored = [(pid, _saturate(score)) for pid, score in zip(self._pattern_ids, raw_scores, strict=True)]
        scored = [pair for pair in scored if pair[1] > 0.0]
        scored.sort(key=lambda pair: pair[1], reverse=True)
        return scored[:top_k]

    def score_for(self, text: str, pattern_ids: list[str]) -> dict[str, float]:
        """Same normalization as `query`, but returns scores for a specific
        set of pattern ids (e.g. ones found only by dense retrieval) rather
        than truncating to top-k — so every persisted match has a real
        lexical score, never a fabricated 0.0."""
        if self._bm25 is None or not pattern_ids:
            return {}
        raw_scores = self._bm25.get_scores(tokenize(text))
        by_id = dict(zip(self._pattern_ids, raw_scores, strict=True))
        return {pid: _saturate(by_id.get(pid, 0.0)) for pid in pattern_ids}
