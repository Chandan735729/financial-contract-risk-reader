"""Retrieval evaluation harness self-correctness tests — Phase 4 spec
SS17/SS24 ("the harness's own correctness").

`test_retrieval_metrics.py` already proves `evaluate_retrieval`'s arithmetic
against hand-computed known answers. This file runs the full synthetic
benchmark (tests/fixtures/retrieval_benchmark.py) end-to-end and pins its
known-good behavior as a regression guard — not a production-accuracy
claim. See the benchmark module's docstring and
corpus/eval/run_retrieval_eval.py.
"""

from __future__ import annotations

import uuid

from app.models import db_models
from app.models.enums import DocumentType
from app.services.retrieval_metrics import evaluate_retrieval
from app.services.retrieval_service import index_corpus_patterns, retrieve_matches
from tests.fixtures.retrieval_benchmark import BENCHMARK_QUERIES, CORPUS_PATTERNS

TAXONOMY_VERSION = "taxonomy_v1"
CORPUS_VERSION = "corpus_v1"


def _seed_benchmark_corpus(db_session) -> list[uuid.UUID]:
    pattern_ids: list[uuid.UUID] = []
    for pattern in CORPUS_PATTERNS:
        row = db_models.CorpusPattern(
            id=uuid.uuid4(),
            pattern_text=pattern["text"],
            risk_category=pattern["risk_category"],
            risk_subcategory=pattern["risk_subcategory"],
            source=pattern["source"],
            taxonomy_version=TAXONOMY_VERSION,
            corpus_version=CORPUS_VERSION,
            is_negative_example=pattern["is_negative_example"],
        )
        db_session.add(row)
        pattern_ids.append(row.id)
    db_session.commit()
    return pattern_ids


def test_benchmark_has_at_least_ten_queries_across_multiple_categories():
    assert len(BENCHMARK_QUERIES) >= 10
    categories = {CORPUS_PATTERNS[q.gold_index]["risk_category"] for q in BENCHMARK_QUERIES}
    assert len(categories) >= 5


def test_every_benchmark_query_runs_without_crashing(db_session, embedding_service, vector_store):
    pattern_ids = _seed_benchmark_corpus(db_session)
    index_corpus_patterns(
        db_session,
        embedding_service=embedding_service,
        vector_store=vector_store,
        taxonomy_version=TAXONOMY_VERSION,
        corpus_version=CORPUS_VERSION,
    )
    for query in BENCHMARK_QUERIES:
        result = retrieve_matches(
            query.text,
            db=db_session,
            embedding_service=embedding_service,
            vector_store=vector_store,
            document_type=DocumentType.UNKNOWN,
            taxonomy_version=TAXONOMY_VERSION,
            corpus_version=CORPUS_VERSION,
            top_k=5,
            min_similarity_floor=0.0,
            min_lexical_floor=0.0,
        )
        assert result is not None
        _ = pattern_ids  # patterns exist; nothing raised


def test_benchmark_recall_and_mrr_meet_known_good_floor(db_session, embedding_service, vector_store):
    # Synthetic, clean-by-construction benchmark — a high floor here is a
    # regression guard, not a production-accuracy claim (see module docstring).
    pattern_ids = _seed_benchmark_corpus(db_session)
    index_corpus_patterns(
        db_session,
        embedding_service=embedding_service,
        vector_store=vector_store,
        taxonomy_version=TAXONOMY_VERSION,
        corpus_version=CORPUS_VERSION,
    )

    ranked_results: list[tuple[list[str], str]] = []
    for query in BENCHMARK_QUERIES:
        result = retrieve_matches(
            query.text,
            db=db_session,
            embedding_service=embedding_service,
            vector_store=vector_store,
            document_type=DocumentType.UNKNOWN,
            taxonomy_version=TAXONOMY_VERSION,
            corpus_version=CORPUS_VERSION,
            top_k=5,
            min_similarity_floor=0.0,
            min_lexical_floor=0.0,
        )
        ranked = [str(m.corpus_pattern_id) for m in result.matches]
        gold_id = str(pattern_ids[query.gold_index])
        ranked_results.append((ranked, gold_id))

    report = evaluate_retrieval(ranked_results)
    assert report.recall_at_3 >= 0.8
    assert report.recall_at_5 >= 0.8
    assert report.mrr >= 0.7


def test_exact_match_queries_always_rank_first(db_session, embedding_service, vector_store):
    pattern_ids = _seed_benchmark_corpus(db_session)
    index_corpus_patterns(
        db_session,
        embedding_service=embedding_service,
        vector_store=vector_store,
        taxonomy_version=TAXONOMY_VERSION,
        corpus_version=CORPUS_VERSION,
    )
    exact_queries = [q for q in BENCHMARK_QUERIES if q.kind == "exact"]
    assert len(exact_queries) >= 3

    for query in exact_queries:
        result = retrieve_matches(
            query.text,
            db=db_session,
            embedding_service=embedding_service,
            vector_store=vector_store,
            document_type=DocumentType.UNKNOWN,
            taxonomy_version=TAXONOMY_VERSION,
            corpus_version=CORPUS_VERSION,
            top_k=5,
            min_similarity_floor=0.0,
            min_lexical_floor=0.0,
        )
        assert result.matches
        assert result.matches[0].corpus_pattern_id == pattern_ids[query.gold_index]
