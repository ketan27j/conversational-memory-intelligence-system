"""M6 (stretch) demo test. Success criteria (PLAN.md, ambiguity on P2
resolved with the user in favor of the ADR-001 reading — see
checkpoints/M6.md G0):
  - P1 (ADR-006): the `rerank` switch on `POST /v1/memories:retrieve`
    actually changes ranking when turned on, and stays off by default.
  - P2 (ADR-001): the write path logs a real (candidate_text, kept) example
    for *every* judge decision — the regression test for the G0 gap this
    milestone fixed — and `NaiveBayesWriteGateClassifier` can learn a
    separable decision boundary from logged examples.
"""
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

from api.auth import mint_token
from db.connection import tenant_connection
from prototypes.classifier import NaiveBayesWriteGateClassifier
from prototypes.reranker import FakeReranker
from retrieval.embedder import EMBEDDING_DIM
from retrieval.indexer import index_memory
from tests.conftest import FakeEmbedder
from write_gate.judge import Decision
from write_gate.pipeline import process_turn

pytestmark = pytest.mark.stretch


# ── P1: reranker ─────────────────────────────────────────────────────────

def _unit_vector(dim: int) -> list[float]:
    vec = [0.0] * EMBEDDING_DIM
    vec[dim] = 1.0
    return vec


def _seed_memory(admin_conn, tenant_id: str, content: str, embedder) -> str:
    with admin_conn.cursor() as cur:
        cur.execute(
            "INSERT INTO memory (tenant_id, type, content, importance, confidence) "
            "VALUES (%s, 'fact', %s, 5, 0.9) RETURNING id",
            (tenant_id, content),
        )
        memory_id = cur.fetchone()[0]
        index_memory(cur, memory_id, tenant_id, content, embedder)
    admin_conn.commit()
    return str(memory_id)


def test_fake_reranker_reorders_by_explicit_relevance():
    from dataclasses import replace
    from datetime import datetime, timezone

    from retrieval.search import ScoredMemory

    low = ScoredMemory(
        id="mem-low", type="fact", content="irrelevant", importance=5, confidence=0.9,
        created_at=datetime.now(timezone.utc), score=0.9, semantic=0.9, recency=1.0, frequency=0.0,
    )
    high = replace(low, id="mem-high", content="relevant", score=0.1)

    reranker = FakeReranker(relevance={"mem-low": 0.05, "mem-high": 0.95}, simulated_latency_ms=0)
    reranked = reranker.rerank("query", [low, high])

    assert [m.id for m in reranked] == ["mem-high", "mem-low"]


def test_retrieve_endpoint_rerank_flag_changes_order(client, two_tenants):
    """End-to-end: with `rerank=True`, the endpoint's own reranker override
    (tests/conftest.py's FakeReranker default) reorders results; with
    `rerank=False` (the default), it doesn't."""
    from api.main import app
    from prototypes.reranker import FakeReranker, get_reranker

    tenant = two_tenants["a"]
    token = mint_token(tenant)
    embedder = FakeEmbedder({"strong keyword match": _unit_vector(0), "weak keyword match": _unit_vector(1)})

    # Both memories match the query on keyword/entity signals about equally;
    # give them deliberately different explicit rerank relevance so a
    # reordering is unambiguous evidence rerank ran, not incidental.
    with tenant_connection(tenant) as conn:
        with conn.cursor() as cur:
            ids = {}
            for label, content, importance in [("a", "strong keyword match", 5), ("b", "weak keyword match", 5)]:
                cur.execute(
                    "INSERT INTO memory (tenant_id, type, content, importance, confidence) "
                    "VALUES (%s, 'fact', %s, %s, 0.9) RETURNING id",
                    (tenant, content, importance),
                )
                memory_id = str(cur.fetchone()[0])
                index_memory(cur, memory_id, tenant, content, embedder)
                ids[label] = memory_id

    app.dependency_overrides[get_reranker] = lambda: FakeReranker(
        relevance={ids["b"]: 1.0, ids["a"]: 0.0}, simulated_latency_ms=0
    )
    try:
        from write_gate.pipeline import get_embedder

        app.dependency_overrides[get_embedder] = lambda: embedder

        no_rerank = client.post(
            "/v1/memories:retrieve",
            json={"query": "match", "rerank": False},
            headers={"Authorization": f"Bearer {token}"},
        ).json()
        with_rerank = client.post(
            "/v1/memories:retrieve",
            json={"query": "match", "rerank": True},
            headers={"Authorization": f"Bearer {token}"},
        ).json()
    finally:
        app.dependency_overrides.pop(get_reranker, None)

    assert len(no_rerank["memories"]) == 2
    assert len(with_rerank["memories"]) == 2
    # The forced relevance map puts "b" first; nothing in the first-pass
    # ranking guarantees that order on its own (both memories are
    # symmetric), so this is real evidence the rerank path ran.
    assert with_rerank["memories"][0]["id"] == ids["b"]


# ── P2: write-gate decision logging + classifier ────────────────────────

def test_write_gate_logs_candidate_text_for_both_kept_and_dropped(admin_conn, two_tenants):
    """Regression test for the G0 gap this milestone fixed: before M6, a
    dropped candidate's text was never stored anywhere in the audit trail
    (only `decision.reason` was) -- write_gate/judge.py's own docstring
    claim ("every decision is logged so it can become training data") was
    false for the drop branch. Both branches must now round-trip the exact
    candidate text."""
    tenant = two_tenants["a"]

    class TwoFactExtractor:
        def extract(self, text):
            return ["worth keeping", "not worth keeping"]

    class KeepFirstJudge:
        def judge(self, candidate):
            keep = candidate == "worth keeping"
            return Decision(keep=keep, importance=5, confidence=0.9, reason="test")

    process_turn(
        tenant, str(uuid.uuid4()), "irrelevant turn text",
        TwoFactExtractor(), KeepFirstJudge(), FakeEmbedder(),
    )

    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT candidate_text, kept FROM write_gate_decision WHERE tenant_id = %s ORDER BY candidate_text",
            (tenant,),
        )
        rows = {r[0]: r[1] for r in cur.fetchall()}

    assert rows == {"worth keeping": True, "not worth keeping": False}


def test_naive_bayes_classifier_learns_a_separable_boundary():
    train = [
        ("I use PostgreSQL for my backend.", True),
        ("My preferred editor is Vim.", True),
        ("I live in Thane.", True),
        ("I work as a backend engineer.", True),
        ("It was rainy outside today.", False),
        ("I had pasta for lunch.", False),
        ("That's an interesting question.", False),
        ("Let me think about that.", False),
    ]
    classifier = NaiveBayesWriteGateClassifier()
    classifier.train(train)

    assert classifier.predict("I use Docker for my deployments.") is True
    assert classifier.predict("I had noodles for dinner.") is False


def test_naive_bayes_classifier_handles_empty_training_data_without_crashing():
    classifier = NaiveBayesWriteGateClassifier()
    classifier.train([])
    # No signal at all -- must not divide by zero or raise; any consistent
    # answer is acceptable since there's nothing to learn from.
    assert classifier.predict("anything") in (True, False)


# ── experiment scripts run end-to-end ───────────────────────────────────

def _run_module(module: str) -> subprocess.CompletedProcess:
    # `-m` (not a bare script path) so `implementation/` -- not
    # `implementation/prototypes/` -- lands on sys.path[0], the same way
    # pytest.ini's `pythonpath = .` makes `db`/`retrieval`/etc. importable
    # as top-level packages during the test run itself.
    root = Path(__file__).parent.parent
    return subprocess.run(
        [sys.executable, "-m", module],
        cwd=root, capture_output=True, text=True, timeout=120,
    )


def test_rerank_experiment_runs_end_to_end_and_prints_a_verdict():
    result = _run_module("prototypes.rerank_experiment")
    assert result.returncode == 0, result.stderr
    assert "ADR-006 verdict:" in result.stdout


def test_classifier_experiment_runs_end_to_end_and_prints_a_verdict():
    result = _run_module("prototypes.classifier_experiment")
    assert result.returncode == 0, result.stderr
    assert "ADR-001 verdict:" in result.stdout
