"""Chroma vector-store wrapper — Technical_Architecture_v2.md SS6/SS7 ("Vector
store (Chroma...) holds corpus embeddings only"), Phase 4 spec SS2.

One Chroma collection per (taxonomy_version, corpus_version) pair. This is
the mechanism that enforces "never silently mix corpus/taxonomy versions
during one analysis" (Phase 4 spec SS7) structurally, not just by
filtering: a query against one version's collection physically cannot
return a pattern indexed under a different version, because it was never
added to that collection.
"""

from __future__ import annotations

import re

import chromadb
from chromadb.api import ClientAPI

_COLLECTION_NAME_SAFE = re.compile(r"[^a-zA-Z0-9_-]")


def _collection_name(taxonomy_version: str, corpus_version: str) -> str:
    safe_taxonomy = _COLLECTION_NAME_SAFE.sub("_", taxonomy_version)
    safe_corpus = _COLLECTION_NAME_SAFE.sub("_", corpus_version)
    return f"corpus_{safe_taxonomy}_{safe_corpus}"


def create_client(persist_dir: str | None) -> ClientAPI:
    """`persist_dir=None` yields an in-process, non-persistent client — used
    by tests and anywhere corpus embeddings are rebuilt fresh each run.
    A configured directory persists across restarts (same local-filesystem
    MVP approach as `upload_dir`; see docs/PROVISIONAL_DECISIONS.md)."""
    if persist_dir:
        return chromadb.PersistentClient(path=persist_dir)
    return chromadb.EphemeralClient()


class ChromaVectorStore:
    def __init__(self, client: ClientAPI) -> None:
        self._client = client

    def _collection(self, taxonomy_version: str, corpus_version: str):
        return self._client.get_or_create_collection(
            _collection_name(taxonomy_version, corpus_version),
            metadata={"hnsw:space": "cosine"},
        )

    def upsert_patterns(
        self,
        *,
        taxonomy_version: str,
        corpus_version: str,
        pattern_ids: list[str],
        embeddings: list[list[float]],
    ) -> None:
        if not pattern_ids:
            return
        collection = self._collection(taxonomy_version, corpus_version)
        collection.upsert(ids=pattern_ids, embeddings=embeddings)

    def query(
        self,
        *,
        taxonomy_version: str,
        corpus_version: str,
        query_embedding: list[float],
        top_k: int,
    ) -> list[tuple[str, float]]:
        """Returns `(corpus_pattern_id, cosine_similarity)` pairs, best
        first. Empty list if the collection doesn't exist yet or holds no
        patterns — never raises for an empty/missing corpus (Phase 4 spec
        SS6, SS17 "empty corpus")."""
        collection = self._collection(taxonomy_version, corpus_version)
        count = collection.count()
        if count == 0:
            return []

        result = collection.query(query_embeddings=[query_embedding], n_results=min(top_k, count))
        ids = result["ids"][0]
        distances = result["distances"][0]
        # Cosine distance = 1 - cosine similarity (collection configured
        # with hnsw:space=cosine) — clamp defensively against floating-point
        # drift pushing similarity fractionally outside [0, 1].
        return [
            (pattern_id, max(0.0, min(1.0, 1.0 - distance)))
            for pattern_id, distance in zip(ids, distances, strict=True)
        ]

    def similarity_for(
        self,
        *,
        taxonomy_version: str,
        corpus_version: str,
        query_embedding: list[float],
        pattern_ids: list[str],
    ) -> dict[str, float]:
        """Looks up the *actual* cosine similarity for a specific set of
        pattern ids (not just whichever happen to be in the top-k) — used
        so a pattern found by lexical-only search still gets a real,
        non-fabricated dense similarity score (Phase 4 spec SS3)."""
        if not pattern_ids:
            return {}
        collection = self._collection(taxonomy_version, corpus_version)
        if collection.count() == 0:
            return {}
        got = collection.get(ids=pattern_ids, include=["embeddings"])
        stored_ids = list(got["ids"])
        stored_embeddings = got["embeddings"]
        scores: dict[str, float] = {}
        query_vector = query_embedding
        for pattern_id, embedding in zip(stored_ids, stored_embeddings, strict=True):
            scores[pattern_id] = _cosine_similarity(query_vector, list(embedding))
        return scores


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(y * y for y in b) ** 0.5
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return max(0.0, min(1.0, dot / (norm_a * norm_b)))
