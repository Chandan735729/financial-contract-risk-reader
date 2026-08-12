"""Hybrid clause-pattern retrieval — Technical_Architecture_v2.md SS3/SS7
("Retrieval Service ... Outputs ranked PatternMatch[] with similarity +
lexical scores, or empty (never forced)"), AI_Risk_Engine_Design.md SS2.

Two independent searches per clause (dense via Chroma + sentence-transformers,
lexical via BM25), never merged into one score here (Phase 4 spec SS3) —
`matched_patterns` persists both `similarity_score` and `lexical_score`
separately; the Risk Engine (Phase 5) combines them.

None of this module decides HIGH/MEDIUM/LOW/UNKNOWN (Phase 4 spec, header).
`retrieve_matches` never raises for the ordinary "nothing found" case — an
empty `RetrievalResult.matches` is the explicit no-signal state (SS6),
never coerced into a fabricated match or a risk label.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.logging import get_logger, log_event
from app.models import db_models
from app.models.enums import DocumentType, RiskCategory
from app.services.embedding_service import EmbeddingService
from app.services.retrieval.lexical import LexicalIndex
from app.services.retrieval.models import PatternMatch, RetrievalResult
from app.services.retrieval.vector_store import ChromaVectorStore

logger = get_logger(__name__)

# Risk_Taxonomy_and_Labeling_Spec.md SS1's per-category `document_type`
# column, encoded as a lookup: which DocumentType values a category is
# considered applicable to. `RiskCategory.OTHER` has no stated document_type
# in the taxonomy (SS1.8: "reserved for genuinely novel risk patterns") —
# treated as unrestricted rather than guessed at. A pattern with no
# risk_category at all is likewise always applicable (nothing to filter on).
_BOTH = frozenset({DocumentType.LOAN, DocumentType.INSURANCE})
RISK_CATEGORY_DOCUMENT_TYPE_APPLICABILITY: dict[RiskCategory, frozenset[DocumentType]] = {
    RiskCategory.FINANCIAL_COST: _BOTH,
    RiskCategory.DEFAULT: frozenset({DocumentType.LOAN}),
    RiskCategory.RENEWAL: _BOTH,
    RiskCategory.LOSS_OF_RIGHTS: _BOTH,
    RiskCategory.INSURANCE: frozenset({DocumentType.INSURANCE}),
    RiskCategory.INTEREST_REPAYMENT: frozenset({DocumentType.LOAN}),
    RiskCategory.TERMINATION: _BOTH,
    RiskCategory.OTHER: _BOTH,
}


def is_category_applicable(risk_category: RiskCategory | None, document_type: DocumentType) -> bool:
    """`document_type=UNKNOWN` is never filtered (Phase 4 spec SS5: "For
    unknown document type: retrieve without inappropriate hard filtering").
    A pattern with no assigned category is never filtered either — there's
    nothing to judge inapplicability against."""
    if document_type is DocumentType.UNKNOWN or risk_category is None:
        return True
    return document_type in RISK_CATEGORY_DOCUMENT_TYPE_APPLICABILITY.get(risk_category, _BOTH)


def _load_corpus_patterns(
    db: Session, *, taxonomy_version: str, corpus_version: str, document_type: DocumentType
) -> list[db_models.CorpusPattern]:
    """Only ever loads patterns matching *both* the expected taxonomy and
    corpus version — patterns from any other version are never candidates,
    which is how "reject incompatible combinations" (Phase 4 spec SS7) is
    enforced: they're never mixed in, not filtered out after the fact."""
    rows = db.scalars(
        select(db_models.CorpusPattern).where(
            db_models.CorpusPattern.taxonomy_version == taxonomy_version,
            db_models.CorpusPattern.corpus_version == corpus_version,
        )
    ).all()
    return [row for row in rows if is_category_applicable(row.risk_category, document_type)]


def index_corpus_patterns(
    db: Session,
    *,
    embedding_service: EmbeddingService,
    vector_store: ChromaVectorStore,
    taxonomy_version: str,
    corpus_version: str,
) -> int:
    """Computes and upserts embeddings for every corpus pattern matching
    this taxonomy/corpus version — a one-time (or re-run-on-corpus-change)
    maintenance step, not something `retrieve_matches` does per clause
    (Phase 4 spec SS22: batch, don't reload/recompute per call).

    Returns the number of patterns indexed. Safe to call with an empty
    corpus (Phase 4 spec SS17 "empty corpus") — indexes nothing, no error.
    """
    rows = db.scalars(
        select(db_models.CorpusPattern).where(
            db_models.CorpusPattern.taxonomy_version == taxonomy_version,
            db_models.CorpusPattern.corpus_version == corpus_version,
        )
    ).all()
    if not rows:
        return 0

    embeddings = embedding_service.embed([row.pattern_text for row in rows])
    vector_store.upsert_patterns(
        taxonomy_version=taxonomy_version,
        corpus_version=corpus_version,
        pattern_ids=[str(row.id) for row in rows],
        embeddings=embeddings,
    )
    return len(rows)


def retrieve_matches(
    clause_text: str,
    *,
    db: Session,
    embedding_service: EmbeddingService,
    vector_store: ChromaVectorStore,
    document_type: DocumentType,
    taxonomy_version: str,
    corpus_version: str,
    top_k: int,
    min_similarity_floor: float,
    min_lexical_floor: float,
) -> RetrievalResult:
    """Runs dense + lexical retrieval independently, unions their top-k
    candidates, and looks up the *actual* score for each candidate under
    both methods (never a fabricated 0.0 for whichever method didn't rank
    it in its own top-k). Returns `matches=()` — explicit no-signal, never
    an exception, never a fake match — when nothing clears either floor.
    """
    candidates = _load_corpus_patterns(
        db, taxonomy_version=taxonomy_version, corpus_version=corpus_version, document_type=document_type
    )
    if not candidates:
        return RetrievalResult(
            matches=(),
            taxonomy_version=taxonomy_version,
            corpus_version=corpus_version,
            document_type_filter_applied=document_type is not DocumentType.UNKNOWN,
            diagnostic="no compatible corpus patterns for this taxonomy/corpus version and document type",
        )

    by_id = {str(row.id): row for row in candidates}
    candidate_ids = list(by_id.keys())

    query_embedding = embedding_service.embed_one(clause_text)
    dense_top_k = vector_store.query(
        taxonomy_version=taxonomy_version,
        corpus_version=corpus_version,
        query_embedding=query_embedding,
        top_k=top_k,
    )
    # Dense results may include ids outside this document-type's candidate
    # set (Chroma indexes the whole corpus, not just the filtered subset) —
    # drop those rather than let a filtered-out category leak back in.
    dense_top_k = [(pid, score) for pid, score in dense_top_k if pid in by_id]

    lexical_index = LexicalIndex(candidate_ids, [by_id[pid].pattern_text for pid in candidate_ids])
    lexical_top_k = lexical_index.query(clause_text, top_k)

    dense_above_floor = {pid for pid, score in dense_top_k if score >= min_similarity_floor}
    lexical_above_floor = {pid for pid, score in lexical_top_k if score >= min_lexical_floor}
    union_ids = list(dense_above_floor | lexical_above_floor)

    if not union_ids:
        return RetrievalResult(
            matches=(),
            taxonomy_version=taxonomy_version,
            corpus_version=corpus_version,
            document_type_filter_applied=document_type is not DocumentType.UNKNOWN,
            diagnostic=None,
        )

    # Every unioned candidate gets its *real* score under both methods, not
    # just whichever it was found by (Phase 4 spec SS3).
    dense_scores = dict(dense_top_k)
    missing_dense = [pid for pid in union_ids if pid not in dense_scores]
    if missing_dense:
        dense_scores.update(
            vector_store.similarity_for(
                taxonomy_version=taxonomy_version,
                corpus_version=corpus_version,
                query_embedding=query_embedding,
                pattern_ids=missing_dense,
            )
        )
    lexical_scores = dict(lexical_top_k)
    missing_lexical = [pid for pid in union_ids if pid not in lexical_scores]
    if missing_lexical:
        lexical_scores.update(lexical_index.score_for(clause_text, missing_lexical))

    dense_found_ids = {pid for pid, _ in dense_top_k}
    lexical_found_ids = {pid for pid, _ in lexical_top_k}

    def _build_match(pid: str) -> PatternMatch:
        pattern = by_id[pid]
        risk_category = pattern.risk_category.value if pattern.risk_category is not None else None
        return PatternMatch(
            corpus_pattern_id=pattern.id,
            similarity_score=dense_scores.get(pid, 0.0),
            lexical_score=lexical_scores.get(pid, 0.0),
            risk_category=risk_category,
            risk_subcategory=pattern.risk_subcategory,
            is_negative_example=pattern.is_negative_example,
            source=pattern.source,
            taxonomy_version=pattern.taxonomy_version,
            corpus_version=pattern.corpus_version,
            found_by_dense=pid in dense_found_ids,
            found_by_lexical=pid in lexical_found_ids,
        )

    matches = tuple(_build_match(pid) for pid in union_ids)
    # Best-first by whichever score is higher — a display/consumption
    # convenience only, not a merged score.
    matches = tuple(sorted(matches, key=lambda m: max(m.similarity_score, m.lexical_score), reverse=True))

    return RetrievalResult(
        matches=matches,
        taxonomy_version=taxonomy_version,
        corpus_version=corpus_version,
        document_type_filter_applied=document_type is not DocumentType.UNKNOWN,
        diagnostic=None,
    )


def persist_matches(
    db: Session, clause_analysis_id: uuid.UUID, result: RetrievalResult
) -> list[db_models.MatchedPattern]:
    """Writes `result.matches` as `matched_patterns` rows — the existing
    schema, no new table (Phase 4 spec SS21). Uses `flush()`, matching the
    Phase 2/3 transaction pattern (caller's `Depends(get_db)` performs the
    final commit)."""
    rows = [
        db_models.MatchedPattern(
            id=uuid.uuid4(),
            clause_analysis_id=clause_analysis_id,
            corpus_pattern_id=match.corpus_pattern_id,
            similarity_score=match.similarity_score,
            lexical_score=match.lexical_score,
        )
        for match in result.matches
    ]
    for row in rows:
        db.add(row)
    db.flush()

    # Safe metadata only — never pattern/clause text (Security_and_Privacy_v2.md SS6).
    log_event(
        logger,
        "retrieval_matches_persisted",
        clause_analysis_id=str(clause_analysis_id),
        count=len(rows),
        taxonomy_version=result.taxonomy_version,
    )
    return rows
