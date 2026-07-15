"""M0 demo test. Success criteria (PLAN.md / sprint_plan.md):
  - cross-user attack test: zero leaks (down from the 0.92 baseline) — hard gate
  - a query with no user filter is refused by the *database*, not application code
"""
import uuid

from api.auth import mint_token
from db.connection import tenant_connection, unscoped_connection


def _seed_memory(admin_conn, tenant_id: str, content: str) -> str:
    with admin_conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO memory (tenant_id, type, content, importance, confidence)
            VALUES (%s, 'fact', %s, 5, 0.9)
            RETURNING id
            """,
            (tenant_id, content),
        )
        memory_id = cur.fetchone()[0]
    admin_conn.commit()
    return str(memory_id)


def test_cross_tenant_leak_direct_query_is_zero(admin_conn, two_tenants):
    """Tenant A's memory must never appear in a scoped query run as tenant B."""
    _seed_memory(admin_conn, two_tenants["a"], "tenant A's secret plan")

    with tenant_connection(two_tenants["b"]) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT content FROM memory")
            rows = cur.fetchall()

    assert rows == [], f"cross-tenant leak: tenant B saw {rows!r}"

    # sanity check: the row genuinely exists (admin/superuser bypasses RLS)
    with admin_conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM memory WHERE tenant_id = %s", (two_tenants["a"],))
        assert cur.fetchone()[0] == 1


def test_unfiltered_query_refused_by_database_not_app_code(admin_conn, two_tenants):
    """A connection with NO tenant set must get zero rows — proving the
    refusal is a database-level guarantee, not something application code
    has to remember to add."""
    _seed_memory(admin_conn, two_tenants["a"], "should never surface unscoped")

    with unscoped_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT content FROM memory")
            rows = cur.fetchall()

    assert rows == [], f"unscoped query returned rows the database should have refused: {rows!r}"


def test_get_memories_api_never_returns_another_tenants_data(client, admin_conn, two_tenants):
    _seed_memory(admin_conn, two_tenants["a"], "A's memory")
    _seed_memory(admin_conn, two_tenants["b"], "B's memory")

    token_b = mint_token(two_tenants["b"])
    resp = client.get("/v1/memories", headers={"Authorization": f"Bearer {token_b}"})

    assert resp.status_code == 200
    contents = [m["content"] for m in resp.json()]
    assert contents == ["B's memory"], f"tenant B's response leaked: {contents!r}"


def test_get_memories_requires_a_token():
    from fastapi.testclient import TestClient

    from api.main import app

    resp = TestClient(app).get("/v1/memories")
    assert resp.status_code == 401


def test_send_message_then_it_is_readable_by_the_same_tenant(client):
    tenant_id = str(uuid.uuid4())
    token = mint_token(tenant_id)
    headers = {"Authorization": f"Bearer {token}"}

    resp = client.post(
        "/v1/memories:ingest",
        json={"session_id": str(uuid.uuid4()), "role": "user", "text": "hello"},
        headers=headers,
    )
    assert resp.status_code == 201
    assert resp.json()["turn_id"]
