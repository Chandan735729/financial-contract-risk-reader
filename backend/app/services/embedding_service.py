"""Thin wrapper around the configured sentence-transformers embedding model
— Technical_Architecture_v2.md SS7 ("dense embedding similarity
(sentence-transformers)"), Phase 4 spec SS8.

The model runs entirely locally (no external API call — Phase 4 spec SS8
explicitly forbids adding one), is loaded exactly once per process via a
cached singleton (`get_embedding_model`), and is never fine-tuned or
retrained here.
"""

from __future__ import annotations

from functools import lru_cache

from sentence_transformers import SentenceTransformer

DEFAULT_MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"


@lru_cache(maxsize=4)
def _load_model(model_name: str) -> SentenceTransformer:
    """Process-global cache keyed by model name — loads the model weights
    from disk/HF cache exactly once, regardless of how many
    `EmbeddingService` instances are created (Phase 4 spec SS8: "model
    loaded once ... no model loading on every clause")."""
    return SentenceTransformer(model_name)


class EmbeddingService:
    """Batch-first embedding wrapper. Deterministic: the same input text
    always produces the same output vector for a given model version — no
    sampling, no randomness."""

    def __init__(self, model_name: str = DEFAULT_MODEL_NAME) -> None:
        self.model_name = model_name
        self._model = _load_model(model_name)

    @property
    def dimension(self) -> int:
        dim = self._model.get_embedding_dimension()
        assert dim is not None, "loaded SentenceTransformer model reported no embedding dimension"
        return int(dim)

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Batch embedding — always prefer this over repeated `embed_one`
        calls (Phase 4 spec SS22: "Embeddings should be batched where
        possible")."""
        if not texts:
            return []
        vectors = self._model.encode(texts, convert_to_numpy=True, normalize_embeddings=True)
        return [vector.tolist() for vector in vectors]

    def embed_one(self, text: str) -> list[float]:
        return self.embed([text])[0]
