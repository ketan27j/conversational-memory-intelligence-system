"""M3 demo test. Success criteria (PLAN.md / sprint_plan.md):
  - outdated preference wins < 0.33 of the time (down from 0.33 baseline),
    aiming near-zero — mechanics covered here; the full benchmark number is
    measured for real in M5's Deliverable-3 rerun, same practice M2 used for
    its 100ms latency claim.
  - replaced memory's history stays there and is auditable (`superseded_by`,
    `audit_log`), never physically removed.

Each test controls FakeEmbedder's vectors explicitly per api_contracts.md's
"repeatable testing" requirement (C14) — no live embedding API call.
"""
import uuid

from api.auth import mint_token
from contradiction.detector import SAME_SUBJECT_THRESHOLD, find_same_subject
from db.connection import tenant_connection
from retrieval.embedder import EMBEDDING_DIM
from retrieval.indexer import index_memory
from tests.conftest import FakeEmbedder, FakeExtractor, FakeJudge
from write_gate.judge import Decision
from write_gate.pipeline import get_embedder, get_extractor, get_judge


def _seed_memory(admin_conn, tenant_id, content, embedder, *, mem_type="fact", confidence=0.5, status="active"):
    with admin_conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO memory (tenant_id, type, content, importance, confidence, status)
            VALUES (%s, %s, %s, 5, %s, %s)
            RETURNING id
            """,
            (tenant_id, mem_type, content, confidence, status),
        )
        memory_id = cur.fetchone()[0]
        index_memory(cur, memory_id, tenant_id, content, embedder)
    admin_conn.commit()
    return str(memory_id)


def _unit_vector(dim: int) -> list[float]:
    vec = [0.0] * EMBEDDING_DIM
    vec[dim] = 1.0
    return vec


# ── detector: same-subject candidates ───────────────────────────────────────

def test_find_same_subject_ignores_non_active_candidates(admin_conn, two_tenants):
    tenant = two_tenants["a"]
    concept = _unit_vector(0)
    embedder = FakeEmbedder({"old fact": concept, "new fact": concept})
    _seed_memory(admin_conn, tenant, "old fact", embedder, status="archived")
    new_id = _seed_memory(admin_conn, tenant, "new fact", embedder)

    with tenant_connection(tenant) as conn:
        with conn.cursor() as cur:
            candidates = find_same_subject(cur, new_id, "fact")

    assert candidates == []


def test_find_same_subject_ignores_other_types(admin_conn, two_tenants):
    tenant = two_tenants["a"]
    concept = _unit_vector(1)
    embedder = FakeEmbedder({"a preference": concept, "a fact": concept})
    _seed_memory(admin_conn, tenant, "a preference", embedder, mem_type="preference")
    new_id = _seed_memory(admin_conn, tenant, "a fact", embedder, mem_type="fact")

    with tenant_connection(tenant) as conn:
        with conn.cursor() as cur:
            candidates = find_same_subject(cur, new_id, "fact")

    assert candidates == [], "a preference must never be treated as the same subject as a fact"


def test_find_same_subject_exempts_events_and_working_memory(admin_conn, two_tenants):
    tenant = two_tenants["a"]
    embedder = FakeEmbedder()
    new_id = _seed_memory(admin_conn, tenant, "launched a thing", embedder, mem_type="event")

    with tenant_connection(tenant) as conn:
        with conn.cursor() as cur:
            assert find_same_subject(cur, new_id, "event") == []
            assert find_same_subject(cur, new_id, "working") == []


def test_find_same_subject_respects_tenant_isolation(admin_conn, two_tenants):
    concept = _unit_vector(2)
    embedder = FakeEmbedder({"tenant a fact": concept, "tenant b fact": concept})
    _seed_memory(admin_conn, two_tenants["a"], "tenant a fact", embedder)
    new_id = _seed_memory(admin_conn, two_tenants["b"], "tenant b fact", embedder)

    with tenant_connection(two_tenants["b"]) as conn:
        with conn.cursor() as cur:
            candidates = find_same_subject(cur, new_id, "fact")

    assert candidates == [], "another tenant's memory must never surface as a same-subject candidate"


def test_find_same_subject_requires_similarity_above_the_floor(admin_conn, two_tenants):
    tenant = two_tenants["a"]
    embedder = FakeEmbedder()  # independent random vectors: near-zero similarity
    _seed_memory(admin_conn, tenant, "totally unrelated old fact", embedder)
    new_id = _seed_memory(admin_conn, tenant, "totally unrelated new fact", embedder)

    with tenant_connection(tenant) as conn:
        with conn.cursor() as cur:
            candidates = find_same_subject(cur, new_id, "fact")

    assert candidates == []
    assert SAME_SUBJECT_THRESHOLD > 0  # sanity: the floor is a real, positive bar


# ── write-time resolution (C8): newer+more-confident wins ──────────────────

def test_higher_confidence_new_memory_supersedes_the_old_one(client, admin_conn, two_tenants):
    tenant = two_tenants["a"]
    old_content = "prefers detailed explanations"
    new_content = "prefers concise explanations"
    concept = _unit_vector(3)
    embedder = FakeEmbedder({old_content: concept, new_content: concept})
    old_id = _seed_memory(admin_conn, tenant, old_content, embedder, confidence=0.4)

    from api.main import app

    app.dependency_overrides[get_extractor] = lambda: FakeExtractor([new_content])
    app.dependency_overrides[get_judge] = lambda: FakeJudge(
        lambda c: Decision(keep=True, importance=5, confidence=0.9, reason="clear preference statement")
    )
    app.dependency_overrides[get_embedder] = lambda: embedder

    token = mint_token(tenant)
    resp = client.post(
        "/v1/memories:ingest",
        json={"session_id": str(uuid.uuid4()), "role": "user", "text": new_content},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201

    with admin_conn.cursor() as cur:
        cur.execute("SELECT status, superseded_by FROM memory WHERE id = %s", (old_id,))
        status, superseded_by = cur.fetchone()
        cur.execute(
            "SELECT count(*) FROM audit_log WHERE tenant_id = %s AND action = 'replaced' AND memory_id = %s",
            (tenant, old_id),
        )
        replaced_count = cur.fetchone()[0]

    assert status == "superseded"
    assert superseded_by is not None
    assert replaced_count == 1


def test_lower_confidence_new_memory_does_not_supersede_the_old_one(client, admin_conn, two_tenants):
    tenant = two_tenants["a"]
    old_content = "prefers detailed explanations"
    new_content = "prefers concise explanations"
    concept = _unit_vector(4)
    embedder = FakeEmbedder({old_content: concept, new_content: concept})
    old_id = _seed_memory(admin_conn, tenant, old_content, embedder, confidence=0.9)

    from api.main import app

    app.dependency_overrides[get_extractor] = lambda: FakeExtractor([new_content])
    app.dependency_overrides[get_judge] = lambda: FakeJudge(
        lambda c: Decision(keep=True, importance=5, confidence=0.3, reason="tentative, low-confidence extraction")
    )
    app.dependency_overrides[get_embedder] = lambda: embedder

    token = mint_token(tenant)
    resp = client.post(
        "/v1/memories:ingest",
        json={"session_id": str(uuid.uuid4()), "role": "user", "text": new_content},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201

    with admin_conn.cursor() as cur:
        cur.execute("SELECT status FROM memory WHERE id = %s", (old_id,))
        old_status = cur.fetchone()[0]
        cur.execute(
            "SELECT status FROM memory WHERE tenant_id = %s AND content = %s", (tenant, new_content)
        )
        new_status = cur.fetchone()[0]

    assert old_status == "active", "a less-confident new memory must not overwrite settled history"
    assert new_status == "active", "both are kept — C8's 'sometimes both are true' case"


# ── the correction endpoint (design/api_contracts.md POST /v1/memories:feedback) ─

def test_feedback_marks_an_active_memory_superseded(client, admin_conn, two_tenants):
    tenant = two_tenants["a"]
    embedder = FakeEmbedder()
    memory_id = _seed_memory(admin_conn, tenant, "some fact", embedder)

    token = mint_token(tenant)
    resp = client.post(
        "/v1/memories:feedback",
        json={"memory_id": memory_id, "signal": "outdated"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert resp.status_code == 200
    assert resp.json() == {"superseded": True, "new_status": "superseded"}

    with admin_conn.cursor() as cur:
        cur.execute("SELECT status FROM memory WHERE id = %s", (memory_id,))
        assert cur.fetchone()[0] == "superseded"
        cur.execute(
            "SELECT count(*) FROM audit_log WHERE tenant_id = %s AND action = 'replaced' AND memory_id = %s",
            (tenant, memory_id),
        )
        assert cur.fetchone()[0] == 1


def test_feedback_on_another_tenants_memory_returns_404(client, admin_conn, two_tenants):
    embedder = FakeEmbedder()
    memory_id = _seed_memory(admin_conn, two_tenants["a"], "tenant a's fact", embedder)

    token = mint_token(two_tenants["b"])
    resp = client.post(
        "/v1/memories:feedback",
        json={"memory_id": memory_id, "signal": "outdated"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert resp.status_code == 404


def test_feedback_on_already_inactive_memory_is_idempotent(client, admin_conn, two_tenants):
    tenant = two_tenants["a"]
    embedder = FakeEmbedder()
    memory_id = _seed_memory(admin_conn, tenant, "archived fact", embedder, status="archived")

    token = mint_token(tenant)
    resp = client.post(
        "/v1/memories:feedback",
        json={"memory_id": memory_id, "signal": "outdated"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert resp.status_code == 200
    assert resp.json() == {"superseded": False, "new_status": "archived"}

    with admin_conn.cursor() as cur:
        cur.execute("SELECT status FROM memory WHERE id = %s", (memory_id,))
        assert cur.fetchone()[0] == "archived", "an already-archived memory must not be silently overwritten"
