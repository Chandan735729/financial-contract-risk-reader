"""Corpus build/seed script — docs/PROVISIONAL_DECISIONS.md P6.8.

Upserts `SEED_PATTERNS` (`corpus/build/seed_patterns.py`) into the
`corpus_patterns` table and rebuilds the matching Chroma collection via
`retrieval_service.index_corpus_patterns`. Idempotent and safe to re-run:
every existing `source="synthetic_seed"` row for the target taxonomy/corpus
version pair is deleted and replaced, rather than accumulating duplicates.

Run from `backend/` (matches `corpus/eval/README.md`'s convention for
running scripts against this repo's environment):

    python ../corpus/build/build_corpus.py

Only ever touches `source="synthetic_seed"` rows — a real corpus (CUAD
subset, permissioned scraped Indian T&Cs) sourced in a future phase would
use a different `source` value and would not be deleted by a re-run of this
script.
"""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_BACKEND_DIR = _REPO_ROOT / "backend"
for _path in (str(_REPO_ROOT), str(_BACKEND_DIR)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from app.core.config import get_settings  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.db.session import create_db_engine, create_session_factory  # noqa: E402
from app.models import db_models  # noqa: E402
from app.services.embedding_service import EmbeddingService  # noqa: E402
from app.services.retrieval.vector_store import ChromaVectorStore, create_client  # noqa: E402
from app.services.retrieval_service import index_corpus_patterns  # noqa: E402
from corpus.build.seed_patterns import SEED_PATTERNS, SOURCE_SYNTHETIC_SEED  # noqa: E402


def build_corpus() -> int:
    settings = get_settings()
    engine = create_db_engine(settings)
    Base.metadata.create_all(engine)
    session_factory = create_session_factory(engine)
    db = session_factory()
    try:
        taxonomy_versions = {p.taxonomy_version for p in SEED_PATTERNS}
        corpus_versions = {p.corpus_version for p in SEED_PATTERNS}
        deleted = (
            db.query(db_models.CorpusPattern)
            .filter(
                db_models.CorpusPattern.source == SOURCE_SYNTHETIC_SEED,
                db_models.CorpusPattern.taxonomy_version.in_(taxonomy_versions),
                db_models.CorpusPattern.corpus_version.in_(corpus_versions),
            )
            .delete(synchronize_session=False)
        )

        for seed in SEED_PATTERNS:
            db.add(
                db_models.CorpusPattern(
                    pattern_text=seed.pattern_text,
                    risk_category=seed.risk_category,
                    risk_subcategory=seed.risk_subcategory,
                    source=seed.source,
                    taxonomy_version=seed.taxonomy_version,
                    annotator_confidence=seed.annotator_confidence,
                    is_negative_example=seed.is_negative_example,
                    corpus_version=seed.corpus_version,
                )
            )
        db.commit()
        print(f"Deleted {deleted} existing synthetic_seed rows; inserted {len(SEED_PATTERNS)} fresh rows.")

        embedding_service = EmbeddingService(model_name=settings.embedding_model_name)
        vector_store = ChromaVectorStore(create_client(settings.chroma_persist_dir))
        indexed_total = 0
        for taxonomy_version in taxonomy_versions:
            for corpus_version in corpus_versions:
                indexed = index_corpus_patterns(
                    db,
                    embedding_service=embedding_service,
                    vector_store=vector_store,
                    taxonomy_version=taxonomy_version,
                    corpus_version=corpus_version,
                )
                indexed_total += indexed
                print(f"Indexed {indexed} patterns for ({taxonomy_version}, {corpus_version}).")
        return indexed_total
    finally:
        db.close()


if __name__ == "__main__":
    build_corpus()
