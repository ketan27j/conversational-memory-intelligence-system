"""Meaning fingerprints for hybrid search (first_principles.md C7).

No embedding provider was pinned by any ADR. Voyage AI is Anthropic's
recommended embedding partner, so it fits the vendor choice the project
already made for the write gate / extractor (both Anthropic-based). Same
swappable-interface pattern as extraction/extractor.py and write_gate/judge.py:
production path is lazy-imported (not a hard dependency), tests inject a
deterministic fake instead of depending on a live API call (C14).
"""
from typing import Protocol

EMBEDDING_DIM = 1536  # must match implementation/db/schema.sql: memory.embedding vector(1536)


class Embedder(Protocol):
    def embed(self, text: str) -> list[float]: ...


class VoyageEmbedder:
    """Production embedder. Requires VOYAGE_API_KEY. Not exercised by the
    offline demo test — see tests/conftest.py's FakeEmbedder."""

    def __init__(self, model: str = "voyage-3-lite"):
        self.model = model

    def embed(self, text: str) -> list[float]:
        import voyageai

        client = voyageai.Client()
        result = client.embed([text], model=self.model, input_type="document")
        vector = list(result.embeddings[0])
        if len(vector) != EMBEDDING_DIM:
            raise ValueError(
                f"{self.model} returned a {len(vector)}-dim vector, expected {EMBEDDING_DIM}"
            )
        return vector
