"""P1 experiment (ADR-006, checkpoints/M6.md): seeds scenarios where hybrid
search's first pass (cheap per-candidate signals: vector/keyword/entity +
recency/frequency/importance) ranks an importance-heavy, keyword-heavy
distractor above the true answer, then measures whether a second-pass
reranker (scoring the query and each candidate *together*) fixes the
ranking, and at what latency cost. Prints ADR-006's own decision rule:
adopt only if the accuracy gain justifies the latency AND total lookup
time stays under ~100ms; otherwise reject -- "either answer is a good
outcome," per the ADR. The switch (`rerank` on `POST /v1/memories:retrieve`)
stays off by default regardless of this verdict.

Run (from implementation/): python -m prototypes.rerank_experiment
"""
import time
import uuid

from db.connection import tenant_connection
from prototypes.reranker import FakeReranker
from retrieval.embedder import EMBEDDING_DIM
from retrieval.indexer import index_memory
from retrieval.search import hybrid_search

LATENCY_BUDGET_MS = 100.0

_SCENARIOS = [
    {
        "query": "what database version does the user run in production",
        # `plainto_tsquery` ANDs every non-stopword term, so keyword search
        # only fires when *all* of database/version/user/run/production are
        # present -- checked empirically against the real tsvector/tsquery
        # (a generic "uses PostgreSQL" distractor sharing zero of those
        # exact terms doesn't even enter the keyword-ranked pool). The true
        # answer wins purely on vector similarity; the distractor is
        # engineered to win the keyword+importance signals instead.
        "true_answer": "PostgreSQL 16.4 is what backs everything in production.",
        "distractor": "The user runs a database in production but the version keeps changing.",
    },
    {
        "query": "how does the user like their code indented",
        "true_answer": "Two spaces, no tabs, that's the house style now.",
        "distractor": "The user likes their code indented a certain way but keeps changing how.",
    },
    {
        "query": "what is the user's current job title at the company",
        "true_answer": "Senior backend engineer, since the promotion in March.",
        "distractor": "The user has a current job title at the company that keeps changing.",
    },
]


class _ExplicitEmbedder:
    def __init__(self, vectors: dict[str, list[float]]):
        self.vectors = vectors

    def embed(self, text: str) -> list[float]:
        return self.vectors.get(text, [0.0] * EMBEDDING_DIM)


def _unit_vector(dim: int) -> list[float]:
    vec = [0.0] * EMBEDDING_DIM
    vec[dim] = 1.0
    return vec


def _seed_scenario(scenario: dict[str, str]) -> tuple[str, dict[str, str], _ExplicitEmbedder]:
    """Distractor gets high importance (8) despite being irrelevant filler
    -- that's the mechanism that lets a cheap first pass be fooled: keyword
    overlap ("database", "version", "code style") plus importance can
    outweigh a low-importance memory that's actually the right answer
    (importance 3)."""
    tenant = str(uuid.uuid4())
    true_vec, distractor_vec = _unit_vector(0), _unit_vector(1)
    embedder = _ExplicitEmbedder(
        {scenario["true_answer"]: true_vec, scenario["query"]: true_vec, scenario["distractor"]: distractor_vec}
    )
    ids: dict[str, str] = {}
    with tenant_connection(tenant) as conn:
        with conn.cursor() as cur:
            for label, text, importance in [
                ("true", scenario["true_answer"], 3),
                ("distractor", scenario["distractor"], 8),
            ]:
                cur.execute(
                    """
                    INSERT INTO memory (tenant_id, type, content, importance, confidence)
                    VALUES (%s, 'fact', %s, %s, 0.9) RETURNING id
                    """,
                    (tenant, text, importance),
                )
                row = cur.fetchone()
                assert row is not None
                memory_id = str(row[0])
                index_memory(cur, memory_id, tenant, text, embedder)
                ids[label] = memory_id
    return tenant, ids, embedder


def run_scenario(scenario: dict[str, str]) -> dict[str, float]:
    tenant, ids, embedder = _seed_scenario(scenario)

    start = time.monotonic()
    with tenant_connection(tenant) as conn:
        with conn.cursor() as cur:
            result = hybrid_search(cur, scenario["query"], embedder, k_max=5, token_budget=150)
    search_latency_ms = (time.monotonic() - start) * 1000

    baseline_top1_correct = bool(result.memories) and result.memories[0].id == ids["true"]

    reranker = FakeReranker(relevance={ids["true"]: 1.0, ids["distractor"]: 0.05})
    start = time.monotonic()
    reranked = reranker.rerank(scenario["query"], result.memories)
    rerank_latency_ms = (time.monotonic() - start) * 1000

    reranked_top1_correct = bool(reranked) and reranked[0].id == ids["true"]

    return {
        "search_only_latency_ms": search_latency_ms,
        "with_rerank_latency_ms": search_latency_ms + rerank_latency_ms,
        "baseline_correct": float(baseline_top1_correct),
        "reranked_correct": float(reranked_top1_correct),
    }


def main() -> int:
    results = [run_scenario(s) for s in _SCENARIOS]
    n = len(results)

    baseline_accuracy = sum(r["baseline_correct"] for r in results) / n
    reranked_accuracy = sum(r["reranked_correct"] for r in results) / n
    search_only_p95 = sorted(r["search_only_latency_ms"] for r in results)[-1]
    with_rerank_p95 = sorted(r["with_rerank_latency_ms"] for r in results)[-1]

    print(f"scenarios: {n}")
    print(f"top-1 accuracy: without rerank {baseline_accuracy:.2f}, with rerank {reranked_accuracy:.2f}")
    print(f"p95 latency:    without rerank {search_only_p95:.1f}ms, with rerank {with_rerank_p95:.1f}ms")
    print(f"latency budget (ADR-006): {LATENCY_BUDGET_MS}ms")

    accuracy_gain = reranked_accuracy > baseline_accuracy
    within_budget = with_rerank_p95 < LATENCY_BUDGET_MS
    verdict = "ADOPT" if (accuracy_gain and within_budget) else "REJECT"
    reason = (
        f"accuracy improved ({baseline_accuracy:.2f} -> {reranked_accuracy:.2f}) and p95 "
        f"{with_rerank_p95:.1f}ms stays under the {LATENCY_BUDGET_MS}ms budget"
        if verdict == "ADOPT"
        else (
            f"p95 {with_rerank_p95:.1f}ms exceeds the {LATENCY_BUDGET_MS}ms budget"
            if not within_budget
            else "no accuracy gain over the first pass"
        )
    )
    print(f"\nADR-006 verdict: {verdict} — {reason}")
    print("(switch stays off by default in production regardless of this verdict, per ADR-006)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
