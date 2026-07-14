"""
Naive memory store: the deliberately simple baseline for D3.

By construction this store:
  - stores EVERY candidate memory          (no admission gate, no dedup, no PII filter)  -> F2, F6
  - ranks on a SINGLE similarity signal     (TF-IDF cosine over raw text)
  - uses NO recency / importance / frequency in ranking                                  -> F3
  - applies NO per-user isolation on retrieval                                           -> F5
  - applies NO relevance threshold (never abstains)                                      -> cold-start
  - performs NO decay / consolidation                                                    -> F7

"Naive" here means minimal, not artificially broken. Each omission corresponds to a
capability (C#) that the first-principles derivation in D1 said the real system needs.
The point of this file is to let those omissions fail measurably.
"""
import time
from dataclasses import dataclass, field

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import linear_kernel


def approx_tokens(text: str) -> int:
    """Rough GPT-style token count (~1.3 tokens per whitespace word).

    An approximation, used only for the context-budget measurement. Stated as an
    approximation in baseline_protocol.md; a real tokenizer would shift absolute
    numbers slightly but not the conclusion.
    """
    return max(1, int(round(len(text.split()) * 1.3)))


@dataclass
class Memory:
    id: int
    user_id: str
    text: str
    created_at: int            # logical turn index; STORED but IGNORED by ranking (that is the point)
    meta: dict = field(default_factory=dict)  # ground-truth labels for evaluation ONLY; the store never reads this


class NaiveMemoryStore:
    def __init__(self):
        self.memories: list[Memory] = []
        self._vectorizer = None
        self._matrix = None
        self._dirty = True

    def add(self, user_id: str, text: str, created_at: int, meta: dict | None = None) -> int:
        """No admission gate, no dedup, no PII filter: everything gets written."""
        mid = len(self.memories)
        self.memories.append(Memory(mid, user_id, text, created_at, meta or {}))
        self._dirty = True
        return mid

    def _ensure_index(self):
        if self._dirty or self._vectorizer is None:
            texts = [m.text for m in self.memories]
            self._vectorizer = TfidfVectorizer(stop_words="english")
            self._matrix = self._vectorizer.fit_transform(texts)
            self._dirty = False

    def _rank(self, query: str):
        self._ensure_index()
        qv = self._vectorizer.transform([query])
        sims = linear_kernel(qv, self._matrix).ravel()
        order = np.argsort(-sims)  # full ranking, all memories
        return order, sims

    def retrieve(self, query: str, k: int = 5, as_user: str | None = None):
        """as_user is accepted and DELIBERATELY IGNORED -> demonstrates the isolation failure (F5)."""
        order, sims = self._rank(query)
        top = order[:k]
        return [(self.memories[i], float(sims[i])) for i in top]

    def full_ranking(self, query: str):
        order, sims = self._rank(query)
        return [(self.memories[i], float(sims[i])) for i in order]

    def retrieve_timed(self, query: str, k: int = 5):
        """Times only per-query retrieval (index assumed pre-built, as in any real system)."""
        self._ensure_index()
        t0 = time.perf_counter()
        qv = self._vectorizer.transform([query])
        sims = linear_kernel(qv, self._matrix).ravel()
        top = np.argsort(-sims)[:k]
        dt_ms = (time.perf_counter() - t0) * 1000.0
        return [(self.memories[i], float(sims[i])) for i in top], dt_ms

    def stats(self) -> dict:
        self._ensure_index()
        raw_bytes = sum(len(m.text.encode("utf-8")) for m in self.memories)
        nnz = int(self._matrix.nnz) if self._matrix is not None else 0
        return {
            "n_memories": len(self.memories),
            "raw_text_bytes": raw_bytes,
            "tfidf_nnz": nnz,
        }
