#!/usr/bin/env python
"""Retrieval evaluation harness — Dataset_and_Evaluation_Spec.md SS5
("Retrieval: Recall@1, Recall@3, Recall@5 ... MRR"), Phase 4 spec SS17/SS24,
**Phase 6 spec SS4** (dense vs. lexical vs. hybrid separated; doc-type,
positive/negative, paraphrase, and terminology-drift breakdowns).

Every unioned candidate `retrieve_matches` returns (with
`min_similarity_floor=min_lexical_floor=0.0`) already carries a real,
non-fabricated score for *both* methods (Phase 4 spec SS3) — so dense-only
and lexical-only rankings are derived by re-sorting that same union by
`similarity_score` / `lexical_score` respectively, rather than issuing
separate retrieval calls. This is exact, not an approximation: any item in
the union not in dense's own top-k necessarily has a `similarity_score` at
or below the dense top-k's cutoff, so re-sorting reproduces dense's own
top-k ranking.

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

_REPO_ROOT = Path(__file__).resolve().parents[2]
_BACKEND_DIR = _REPO_ROOT / "backend"
for _path in (str(_REPO_ROOT), str(_BACKEND_DIR)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import os  # noqa: E402

os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from app.core.config import Settings  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.db.session import create_db_engine, create_session_factory  # noqa: E402
from app.models import db_models  # noqa: E402
from app.models.enums import DocumentType  # noqa: E402
from app.services.embedding_service import EmbeddingService  # noqa: E402
from app.services.retrieval.models import PatternMatch  # noqa: E402
from app.services.retrieval.vector_store import ChromaVectorStore, create_client  # noqa: E402
from app.services.retrieval_metrics import RetrievalEvalReport, evaluate_retrieval  # noqa: E402
from app.services.retrieval_service import index_corpus_patterns, retrieve_matches  # noqa: E402
from corpus.eval.datasets.retrieval_terminology_drift import TERMINOLOGY_DRIFT_QUERIES  # noqa: E402
from tests.fixtures.retrieval_benchmark import BENCHMARK_QUERIES, CORPUS_PATTERNS  # noqa: E402

TAXONOMY_VERSION = "taxonomy_v1"
CORPUS_VERSION = "corpus_v1"


def _rank(matches: tuple[PatternMatch, ...], key: str) -> list[str]:
    scored = sorted(matches, key=lambda m: getattr(m, key), reverse=True)
    return [str(m.corpus_pattern_id) for m in scored]


def _report_line(label: str, report: RetrievalEvalReport) -> str:
    return (
        f"{label:32s} n={report.query_count:3d}  "
        f"R@1={report.recall_at_1:.2f}  R@3={report.recall_at_3:.2f}  "
        f"R@5={report.recall_at_5:.2f}  MRR={report.mrr:.2f}"
    )


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

    def run_all(document_type: DocumentType) -> dict[str, tuple[PatternMatch, ...]]:
        results: dict[str, tuple[PatternMatch, ...]] = {}
        for query in BENCHMARK_QUERIES:
            result = retrieve_matches(
                query.text,
                db=db,
                embedding_service=embedding_service,
                vector_store=vector_store,
                document_type=document_type,
                taxonomy_version=TAXONOMY_VERSION,
                corpus_version=CORPUS_VERSION,
                top_k=5,
                min_similarity_floor=0.0,
                min_lexical_floor=0.0,
            )
            results[query.text] = result.matches
        return results

    print(f"Retrieval evaluation - {len(BENCHMARK_QUERIES)} synthetic benchmark queries")
    print("=" * 90)

    # ---- 1. Dense vs. lexical vs. hybrid (document_type=UNKNOWN, current default) ----
    raw_matches_unknown = run_all(DocumentType.UNKNOWN)

    def build_pairs(rank_key: str | None) -> list[tuple[list[str], str]]:
        pairs = []
        for query in BENCHMARK_QUERIES:
            matches = raw_matches_unknown[query.text]
            ranked = (
                [str(m.corpus_pattern_id) for m in matches] if rank_key is None else _rank(matches, rank_key)
            )
            gold_id = str(pattern_ids[query.gold_index])
            pairs.append((ranked, gold_id))
        return pairs

    dense_report = evaluate_retrieval(build_pairs("similarity_score"))
    lexical_report = evaluate_retrieval(build_pairs("lexical_score"))
    hybrid_report = evaluate_retrieval(build_pairs(None))

    print("\n-- Mechanism comparison (does the hybrid union actually help?) --")
    print(_report_line("dense_only", dense_report))
    print(_report_line("lexical_only", lexical_report))
    print(_report_line("hybrid_union", hybrid_report))
    if hybrid_report.recall_at_5 <= max(dense_report.recall_at_5, lexical_report.recall_at_5):
        print(
            "  NOTE: hybrid_union did not exceed the best single mechanism on this benchmark "
            "(small synthetic set - not a claim that hybrid retrieval is unhelpful in general)."
        )

    # ---- 2. Positive vs. negative examples ----
    positive_pairs: list[tuple[list[str], str]] = []
    negative_pairs: list[tuple[list[str], str]] = []
    for query, (ranked, gold_id) in zip(BENCHMARK_QUERIES, build_pairs(None), strict=True):
        is_negative = CORPUS_PATTERNS[query.gold_index]["is_negative_example"]
        (negative_pairs if is_negative else positive_pairs).append((ranked, gold_id))

    print("\n-- Positive vs. negative gold examples (hybrid) --")
    print(_report_line("positive_examples", evaluate_retrieval(positive_pairs)))
    if negative_pairs:
        print(_report_line("negative_examples", evaluate_retrieval(negative_pairs)))
    else:
        print("negative_examples: no benchmark query targets a negative-example gold pattern")

    # ---- 3. Exact vs. paraphrase ----
    print("\n-- Query kind (hybrid) --")
    for kind in sorted({q.kind for q in BENCHMARK_QUERIES}):
        kind_pairs = [
            (ranked, gold_id)
            for query, (ranked, gold_id) in zip(BENCHMARK_QUERIES, build_pairs(None), strict=True)
            if query.kind == kind
        ]
        print(_report_line(kind, evaluate_retrieval(kind_pairs)))

    # ---- 4. Terminology drift (supplementary set) ----
    drift_pairs = []
    for drift_query in TERMINOLOGY_DRIFT_QUERIES:
        result = retrieve_matches(
            drift_query.text,
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
        drift_pairs.append((ranked, str(pattern_ids[drift_query.gold_index])))
    print("\n-- Terminology drift (heavy vocabulary substitution, hybrid) --")
    print(_report_line("terminology_drift", evaluate_retrieval(drift_pairs)))

    # ---- 5. Known vs. unknown document type (does hard filtering help/hurt?) ----
    print("\n-- document_type filtering (hybrid) --")
    for doc_type in (DocumentType.UNKNOWN, DocumentType.LOAN, DocumentType.INSURANCE):
        raw_matches = run_all(doc_type)
        pairs = []
        for query in BENCHMARK_QUERIES:
            matches = raw_matches[query.text]
            ranked = [str(m.corpus_pattern_id) for m in matches]
            pairs.append((ranked, str(pattern_ids[query.gold_index])))
        print(_report_line(f"document_type={doc_type.value}", evaluate_retrieval(pairs)))

    print()
    print(
        "NOTE: synthetic benchmark only - not production retrieval accuracy. "
        "See Dataset_and_Evaluation_Spec.md SS4 for the real-world benchmark this does not replace."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
