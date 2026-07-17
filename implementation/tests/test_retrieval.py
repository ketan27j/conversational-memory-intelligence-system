"""M2 demo test. Success criteria (PLAN.md / sprint_plan.md):
  - stays silent (abstains) on unanswerable questions instead of guessing
  - exact-fact questions are answered correctly (F4 — keyword search catches
    what vector search alone would miss, per ADR-002's D3 finding)
  - lookups finish under 100ms at every store size (smoke-checked here;
    the full-scale timing claim is M5's Deliverable-3 benchmark rerun)

Each test controls FakeEmbedder's vectors explicitly per api_contracts.md's
"repeatable testing" requirement (C14) — no live embedding API call.
"""
import time

from api.auth import mint_token
from db.connection import tenant_connection
from retrieval.embedder import EMBEDDING_DIM
from retrieval.indexer import index_memory
from retrieval.search import hybrid_search
from tests.conftest import FakeEmbedder


def _seed_memory(admin_conn, tenant_id, content, embedder, *, importance=5, confidence=0.9, access_count=0):
    with admin_conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO memory (tenant_id, type, content, importance, confidence, access_count)
            VALUES (%s, 'fact', %s, %s, %s, %s)
            RETURNING id
            """,
            (tenant_id, content, importance, confidence, access_count),
        )
        memory_id = cur.fetchone()[0]
        index_memory(cur, memory_id, tenant_id, content, embedder)
    admin_conn.commit()
    return str(memory_id)


def _unit_vector(dim: int) -> list[float]:
    vec = [0.0] * EMBEDDING_DIM
    vec[dim] = 1.0
    return vec


# ── indexer: write-time embedding + entity population ──────────────────────

def test_index_memory_populates_embedding_and_entities(admin_conn, two_tenants):
    tenant = two_tenants["a"]
    content = "Uses PostgreSQL and acme_tools"
    embedder = FakeEmbedder({content: _unit_vector(0)})

    memory_id = _seed_memory(admin_conn, tenant, content, embedder)

    with admin_conn.cursor() as cur:
        cur.execute("SELECT embedding IS NOT NULL FROM memory WHERE id = %s", (memory_id,))
        assert cur.fetchone()[0] is True
        cur.execute(
            "SELECT entity FROM memory_entity WHERE memory_id = %s ORDER BY entity", (memory_id,)
        )
        entities = [row[0] for row in cur.fetchall()]
    assert "postgresql" in entities
    assert "acme_tools" in entities


# ── hybrid search: the three signals (C7) ───────────────────────────────────

def test_finds_exact_keyword_match_despite_low_semantic_similarity(admin_conn, two_tenants):
    """F4 fix (ADR-002): keyword search alone catches this even when the
    embeddings for these two independently-hashed strings are near-orthogonal."""
    tenant = two_tenants["a"]
    embedder = FakeEmbedder()
    _seed_memory(admin_conn, tenant, "Uses PostgreSQL 16.4 in production", embedder)

    with tenant_connection(tenant) as conn:
        with conn.cursor() as cur:
            result = hybrid_search(cur, "does the user use postgresql", embedder)

    assert result.abstained is False
    assert any("PostgreSQL" in m.content for m in result.memories)


def test_finds_semantic_match_with_zero_keyword_overlap(admin_conn, two_tenants):
    """Content and query share no words at all — only the (faked) meaning
    vector links them, proving vector search contributes independently of
    keyword search."""
    tenant = two_tenants["a"]
    content = "Prefers concise replies without extra caveats"
    query = "how thorough should explanations be for this person"
    concept = _unit_vector(1)
    embedder = FakeEmbedder({content: concept, query: concept})
    _seed_memory(admin_conn, tenant, content, embedder)

    with tenant_connection(tenant) as conn:
        with conn.cursor() as cur:
            result = hybrid_search(cur, query, embedder)

    assert result.abstained is False
    assert result.memories[0].content == content
    assert result.signals["semantic"] >= 0.5


def test_relevant_answer_survives_an_unrelated_recent_important_distractor(admin_conn, two_tenants):
    """L4 VERIFY regression (checkpoints/M2.md): the relevance floor must
    filter per-candidate, not gate on the single top-by-final-score item.
    An unrelated memory with high importance/recency/frequency must not be
    able to out-rank a genuinely relevant answer and then fail the bar for
    the whole query, causing a false abstention on an answerable question."""
    tenant = two_tenants["a"]
    distractor = "The office coffee machine was replaced last week"
    answer = "Runs postgresql 16.4 in production"
    query = "what version of postgresql does the user run"
    embedder = FakeEmbedder()  # independent random vectors: near-zero similarity for both

    # Distractor: high importance, fresh, already accessed a lot — every
    # non-semantic signal maxed out, despite being wholly unrelated.
    _seed_memory(admin_conn, tenant, distractor, embedder, importance=10, access_count=1000)
    # Answer: low importance, so it only wins if semantic relevance counts.
    _seed_memory(admin_conn, tenant, answer, embedder, importance=1, access_count=0)

    with tenant_connection(tenant) as conn:
        with conn.cursor() as cur:
            result = hybrid_search(cur, query, embedder)

    assert result.abstained is False, "a distractor must never suppress a genuinely relevant answer"
    assert any(m.content == answer for m in result.memories)


def test_abstains_when_nothing_is_relevant(admin_conn, two_tenants):
    """INV-6: honest 'I don't know' instead of guessing — the cold-start
    failure the naive baseline always got wrong."""
    tenant = two_tenants["a"]
    embedder = FakeEmbedder()
    _seed_memory(admin_conn, tenant, "Uses PostgreSQL for the memory store", embedder)

    with tenant_connection(tenant) as conn:
        with conn.cursor() as cur:
            result = hybrid_search(
                cur, "what is the user's favorite holiday destination", embedder
            )

    assert result.abstained is True
    assert result.memories == []


def test_high_importance_and_recent_wins_the_tie(admin_conn, two_tenants):
    """C6: ranking uses more than similarity — when semantic signals are
    effectively tied, importance breaks the tie."""
    tenant = two_tenants["a"]
    query = "what does the user prefer for code style"
    low = "Prefers tabs for indentation in code files"
    high = "Prefers tabs for indentation in code files indeed"
    concept = _unit_vector(2)
    embedder = FakeEmbedder({query: concept, low: concept, high: concept})
    _seed_memory(admin_conn, tenant, low, embedder, importance=2)
    _seed_memory(admin_conn, tenant, high, embedder, importance=9)

    with tenant_connection(tenant) as conn:
        with conn.cursor() as cur:
            result = hybrid_search(cur, query, embedder)

    assert result.memories[0].content == high


# ── INV-3: token budget is a hard cap ───────────────────────────────────────

def test_never_exceeds_token_budget(admin_conn, two_tenants):
    tenant = two_tenants["a"]
    query = "tell me about the user's PostgreSQL setup"
    contents = [
        f"Uses PostgreSQL version {i} in the staging cluster with extra detail padding words here"
        for i in range(4)
    ]
    concept = _unit_vector(3)
    embedder = FakeEmbedder({query: concept, **{c: concept for c in contents}})
    for c in contents:
        _seed_memory(admin_conn, tenant, c, embedder)

    with tenant_connection(tenant) as conn:
        with conn.cursor() as cur:
            result = hybrid_search(cur, query, embedder, token_budget=20, k_max=8)

    assert result.abstained is False
    assert result.tokens_used <= 20
    assert len(result.memories) < len(contents), "budget must have excluded at least one candidate"


# ── INV-1 still holds on the new query paths ────────────────────────────────

def test_hybrid_search_never_returns_another_tenants_memory(admin_conn, two_tenants):
    content = "Uses PostgreSQL for tenant A only"
    query = "does the user use postgresql"
    embedder = FakeEmbedder({content: _unit_vector(4), query: _unit_vector(4)})
    _seed_memory(admin_conn, two_tenants["a"], content, embedder)

    with tenant_connection(two_tenants["b"]) as conn:
        with conn.cursor() as cur:
            result = hybrid_search(cur, query, embedder)

    assert result.abstained is True
    assert result.memories == []


# ── latency smoke check (full-scale timing claim is M5's benchmark rerun) ──

def test_latency_smoke_check_over_a_modest_store(admin_conn, two_tenants):
    tenant = two_tenants["a"]
    embedder = FakeEmbedder()
    for i in range(150):
        _seed_memory(admin_conn, tenant, f"Fact number {i} about various unrelated things", embedder)

    with tenant_connection(tenant) as conn:
        with conn.cursor() as cur:
            start = time.perf_counter()
            hybrid_search(cur, "fact number 42", embedder)
            elapsed_ms = (time.perf_counter() - start) * 1000

    assert elapsed_ms < 500, f"hybrid_search took {elapsed_ms:.1f}ms for 150 memories"


# ── the HTTP contract (design/api_contracts.md POST /v1/memories:retrieve) ─

def test_retrieve_endpoint_returns_scored_memories(client, admin_conn, two_tenants):
    from api.main import app
    from write_gate.pipeline import get_embedder

    tenant = two_tenants["a"]
    content = "Uses PostgreSQL as the primary database"
    query = "what database does the user use"
    concept = _unit_vector(5)
    embedder = FakeEmbedder({content: concept, query: concept})
    app.dependency_overrides[get_embedder] = lambda: embedder
    _seed_memory(admin_conn, tenant, content, embedder)

    token = mint_token(tenant)
    resp = client.post(
        "/v1/memories:retrieve",
        json={"query": query, "token_budget": 512, "k_max": 8},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["abstained"] is False
    assert body["memories"][0]["content"] == content
    assert "semantic" in body["signals"]


def test_retrieve_endpoint_abstains_with_empty_store(client, two_tenants):
    token = mint_token(two_tenants["a"])
    resp = client.post(
        "/v1/memories:retrieve",
        json={"query": "anything at all"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["abstained"] is True
    assert body["memories"] == []
