#!/usr/bin/env python
"""Retrieval evaluation harness — Dataset_and_Evaluation_Spec.md SS5
("Retrieval: Recall@1, Recall@3, Recall@5 ... MRR"), Phase 4 spec SS17/SS24.

Runs hybrid retrieval against the synthetic benchmark
(backend/tests/fixtures/retrieval_benchmark.py) and reports Recall@1/3/5
and MRR, using the union of dense+lexical ranking (best score first) as the
ranked list scored against each query's known-correct pattern.

IMPORTANT — READ BEFORE CITING THESE NUMBERS:
This benchmark is synthetic and hand-authored for development/regression
purposes — NOT the real-world benchmark Dataset_and_Evaluation_Spec.md SS4
requires. These numbers demonstrate the harness works and give a
directional sanity check against known structural patterns; they say
nothing about production retrieval performance on real, messy financial
contracts. Do not report these numbers as production accuracy.

Usage: (from backend/, so `app` is importable)
    python ../corpus/eval/run_retrieval_eval.py
"""

from __future__ import annotations

import sys
import uuid
from pathlib import Path

_BACKEND_DIR = Path(__file__).resolve().parents[2] / "backend"
sys.path.insert(0, str(_BACKEND_DIR))

import os  # noqa: E402

os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from app.core.config import Settings  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.db.session import create_db_engine, create_session_factory  # noqa: E402
from app.models import db_models  # noqa: E402
from app.models.enums import DocumentType  # noqa: E402
from app.services.embedding_service import EmbeddingService  # noqa: E402
from app.services.retrieval.vector_store import ChromaVectorStore, create_client  # noqa: E402
from app.services.retrieval_metrics import evaluate_retrieval  # noqa: E402
from app.services.retrieval_service import index_corpus_patterns, retrieve_matches  # noqa: E402
from tests.fixtures.retrieval_benchmark import BENCHMARK_QUERIES, CORPUS_PATTERNS  # noqa: E402

TAXONOMY_VERSION = "taxonomy_v1"
CORPUS_VERSION = "corpus_v1"


def main() -> int:
    settings = Settings(environment="test", database_url="sqlite:///:memory:")
    engine = create_db_engine(settings)
    Base.metadata.create_all(engine)
    db = create_session_factory(engine)()

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
        db.add(row)
        pattern_ids.append(row.id)
    db.commit()

    embedding_service = EmbeddingService()
    vector_store = ChromaVectorStore(create_client(None))
    index_corpus_patterns(
        db,
        embedding_service=embedding_service,
        vector_store=vector_store,
        taxonomy_version=TAXONOMY_VERSION,
        corpus_version=CORPUS_VERSION,
    )

    ranked_results: list[tuple[list[str], str]] = []
    print(f"Retrieval evaluation — {len(BENCHMARK_QUERIES)} synthetic benchmark queries")
    print("=" * 78)
    print(f"{'kind':12s} {'gold_subcategory':24s} {'top-1 subcategory':24s} {'rank':>5s}")
    print("-" * 78)

    for query in BENCHMARK_QUERIES:
        result = retrieve_matches(
            query.text,
            db=db,
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

        rank = (ranked.index(gold_id) + 1) if gold_id in ranked else -1
        top_subcategory = result.matches[0].risk_subcategory if result.matches else "(none)"
        gold_subcategory = CORPUS_PATTERNS[query.gold_index]["risk_subcategory"]
        print(f"{query.kind:12s} {gold_subcategory:24s} {top_subcategory:24s} {rank:>5d}")

    report = evaluate_retrieval(ranked_results)
    print("-" * 78)
    print(f"Recall@1: {report.recall_at_1:.2f}")
    print(f"Recall@3: {report.recall_at_3:.2f}")
    print(f"Recall@5: {report.recall_at_5:.2f}")
    print(f"MRR:      {report.mrr:.2f}")
    print()
    print(
        "NOTE: synthetic benchmark only — not production retrieval accuracy. "
        "See Dataset_and_Evaluation_Spec.md SS4 for the real-world benchmark this does not replace."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
