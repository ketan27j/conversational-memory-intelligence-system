"""P1 (ADR-006): a second, slower, more careful pass that re-scores hybrid
search's top candidates against the query together, rather than comparing
each candidate to the query in isolation the way the first pass's vector/
keyword/entity signals do. Ships behind the `rerank` switch on
`POST /v1/memories:retrieve` (accepted at M2, wired up for real here) —
off by default per ADR-006, regardless of what `rerank_experiment.py`
concludes.

Same swappable-interface-plus-fake pattern as every other LLM-backed
component in this codebase (write_gate/judge.py, extraction/extractor.py):
production path is a live LLM call, the demo test suite injects a
deterministic fake instead (C14).
"""
import time
from dataclasses import replace
from typing import Protocol

from retrieval.search import ScoredMemory


class Reranker(Protocol):
    def rerank(self, query: str, candidates: list[ScoredMemory]) -> list[ScoredMemory]: ...


class AnthropicReranker:
    """Production reranker. Requires ANTHROPIC_API_KEY. Not exercised by the
    offline demo test — see FakeReranker below."""

    def __init__(self, model: str = "claude-haiku-4-5"):
        self.model = model

    def rerank(self, query: str, candidates: list[ScoredMemory]) -> list[ScoredMemory]:
        import json

        import anthropic

        client = anthropic.Anthropic()
        rescored = []
        for candidate in candidates:
            prompt = (
                "On a scale of 0.0 to 1.0, how relevant is this memory to answering "
                "the question? Answer as JSON only: {\"relevance\": 0.0-1.0}.\n\n"
                f"Question: {query!r}\nMemory: {candidate.content!r}"
            )
            resp = client.messages.create(
                model=self.model,
                max_tokens=50,
                messages=[{"role": "user", "content": prompt}],
            )
            data = json.loads(resp.content[0].text)
            rescored.append(replace(candidate, score=float(data["relevance"])))
        return sorted(rescored, key=lambda m: m.score, reverse=True)


def get_reranker() -> Reranker:
    return AnthropicReranker()


class FakeReranker:
    """Deterministic stand-in for AnthropicReranker (C14). Scores by a
    caller-supplied relevance map instead of an LLM call, and sleeps for
    `simulated_latency_ms` per candidate so the latency half of the ADR-006
    experiment reflects a genuine per-candidate LLM round trip's order of
    magnitude rather than a suspiciously-instant fake — an experiment that
    can't produce an honest "reject, too slow" outcome isn't testing
    anything ADR-006 actually asked."""

    def __init__(self, relevance: dict[str, float] | None = None, simulated_latency_ms: float = 80.0):
        self.relevance = relevance or {}
        self.simulated_latency_ms = simulated_latency_ms

    def rerank(self, query: str, candidates: list[ScoredMemory]) -> list[ScoredMemory]:
        rescored = []
        for candidate in candidates:
            time.sleep(self.simulated_latency_ms / 1000)
            new_score = self.relevance.get(candidate.id, candidate.score)
            rescored.append(replace(candidate, score=new_score))
        return sorted(rescored, key=lambda m: m.score, reverse=True)
