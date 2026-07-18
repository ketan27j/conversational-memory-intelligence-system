"""M4 demo test. Success criteria (PLAN.md):
  - store stops growing unboundedly under constant writes (reweight + archive)
  - frequently-used memories are not archived by mistake
  - deletion: gone from reads instantly, gone from search within 60s — INV-4
    hard gate

No real 60-second sleep is used anywhere here — `run_purge_job` is called
directly, same "test the job function itself" precedent M1-M3 used for their
own background-job-shaped work (ADR-005's BackgroundTasks, the nightly
contradiction check).
"""
from api.auth import mint_token
from db.connection import job_connection
from forgetting.purge import run_purge_job
from forgetting.reweight import ARCHIVE_FLOOR, run_reweight_job


def _seed_memory(
    admin_conn,
    tenant_id,
    content,
    *,
    importance=5,
    confidence=0.5,
    status="active",
    access_count=0,
    created_days_ago=0.0,
    last_accessed_days_ago=None,
):
    with admin_conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO memory
                (tenant_id, type, content, importance, confidence, status,
                 access_count, created_at, last_accessed_at)
            VALUES (%s, 'fact', %s, %s, %s, %s, %s,
                    now() - (%s::text || ' days')::interval,
                    CASE WHEN %s::float8 IS NULL THEN NULL
                         ELSE now() - (%s::text || ' days')::interval END)
            RETURNING id
            """,
            (
                tenant_id,
                content,
                importance,
                confidence,
                status,
                access_count,
                created_days_ago,
                last_accessed_days_ago,
                last_accessed_days_ago,
            ),
        )
        memory_id = cur.fetchone()[0]
    admin_conn.commit()
    return str(memory_id)


# ── reweight: recompute weight, archive below the floor (C9) ───────────────

def test_reweight_archives_a_stale_unimportant_never_accessed_memory(admin_conn, two_tenants):
    tenant = two_tenants["a"]
    memory_id = _seed_memory(
        admin_conn, tenant, "an old, unimportant fact",
        importance=1, access_count=0, created_days_ago=200,
    )

    with job_connection() as conn:
        with conn.cursor() as cur:
            result = run_reweight_job(cur)

    assert memory_id in result.archived_ids
    with admin_conn.cursor() as cur:
        cur.execute("SELECT status, weight FROM memory WHERE id = %s", (memory_id,))
        status, weight = cur.fetchone()
        cur.execute(
            "SELECT count(*) FROM audit_log WHERE tenant_id = %s AND action = 'archived' AND memory_id = %s",
            (tenant, memory_id),
        )
        archived_count = cur.fetchone()[0]

    assert status == "archived"
    assert weight < ARCHIVE_FLOOR
    assert archived_count == 1


def test_reweight_keeps_a_frequently_used_memory_despite_old_created_at(admin_conn, two_tenants):
    tenant = two_tenants["a"]
    memory_id = _seed_memory(
        admin_conn, tenant, "a fact everyone keeps asking about",
        importance=5, access_count=50, created_days_ago=200, last_accessed_days_ago=1,
    )

    with job_connection() as conn:
        with conn.cursor() as cur:
            result = run_reweight_job(cur)

    assert memory_id not in result.archived_ids
    with admin_conn.cursor() as cur:
        cur.execute("SELECT status FROM memory WHERE id = %s", (memory_id,))
        assert cur.fetchone()[0] == "active", "frequently-used memories must not be archived by mistake"


def test_reweight_gives_a_brand_new_unaccessed_memory_a_grace_period(admin_conn, two_tenants):
    tenant = two_tenants["a"]
    memory_id = _seed_memory(
        admin_conn, tenant, "a fact written moments ago",
        importance=8, access_count=0, created_days_ago=0,
    )

    with job_connection() as conn:
        with conn.cursor() as cur:
            result = run_reweight_job(cur)

    assert memory_id not in result.archived_ids
    with admin_conn.cursor() as cur:
        cur.execute("SELECT status FROM memory WHERE id = %s", (memory_id,))
        assert cur.fetchone()[0] == "active", "a never-yet-retrieved memory must survive its first job run"


def test_reweight_persists_the_recomputed_weight_for_survivors(admin_conn, two_tenants):
    tenant = two_tenants["a"]
    memory_id = _seed_memory(
        admin_conn, tenant, "a middling fact",
        importance=5, access_count=0, created_days_ago=0,
    )

    with job_connection() as conn:
        with conn.cursor() as cur:
            run_reweight_job(cur)

    with admin_conn.cursor() as cur:
        cur.execute("SELECT weight FROM memory WHERE id = %s", (memory_id,))
        weight = cur.fetchone()[0]
    assert weight == 0.5, "importance 5 / 10 * recency 1.0 * usefulness 1.0 == 0.5"


def test_reweight_is_correct_across_tenants_in_one_pass(admin_conn, two_tenants):
    stale_id = _seed_memory(
        admin_conn, two_tenants["a"], "tenant a's stale fact",
        importance=1, access_count=0, created_days_ago=200,
    )
    fresh_id = _seed_memory(
        admin_conn, two_tenants["b"], "tenant b's fresh important fact",
        importance=9, access_count=0, created_days_ago=0,
    )

    with job_connection() as conn:
        with conn.cursor() as cur:
            result = run_reweight_job(cur)

    assert stale_id in result.archived_ids
    assert fresh_id not in result.archived_ids
    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM audit_log WHERE tenant_id = %s AND memory_id = %s AND action = 'archived'",
            (two_tenants["a"], stale_id),
        )
        assert cur.fetchone()[0] == 1
        cur.execute(
            "SELECT count(*) FROM audit_log WHERE tenant_id = %s AND memory_id = %s",
            (two_tenants["b"], stale_id),
        )
        assert cur.fetchone()[0] == 0, "tenant a's archive event must never be logged under tenant b"


# ── purge: finish pending deletions (C11, INV-4) ────────────────────────────

def test_purge_hard_deletes_a_memory_marked_deleted(admin_conn, two_tenants):
    tenant = two_tenants["a"]
    memory_id = _seed_memory(admin_conn, tenant, "a memory the user deleted", status="deleted")

    with job_connection() as conn:
        with conn.cursor() as cur:
            result = run_purge_job(cur)

    assert memory_id in result.purged_ids
    with admin_conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM memory WHERE id = %s", (memory_id,))
        assert cur.fetchone()[0] == 0, "a purged memory must be physically gone, not just re-flagged"
        cur.execute(
            "SELECT count(*) FROM audit_log WHERE tenant_id = %s AND action = 'deleted' AND memory_id = %s",
            (tenant, memory_id),
        )
        assert cur.fetchone()[0] == 1


def test_purge_ignores_active_memories(admin_conn, two_tenants):
    tenant = two_tenants["a"]
    memory_id = _seed_memory(admin_conn, tenant, "a memory nobody deleted", status="active")

    with job_connection() as conn:
        with conn.cursor() as cur:
            result = run_purge_job(cur)

    assert memory_id not in result.purged_ids
    with admin_conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM memory WHERE id = %s", (memory_id,))
        assert cur.fetchone()[0] == 1


def test_purge_cascades_to_memory_entity(admin_conn, two_tenants):
    tenant = two_tenants["a"]
    memory_id = _seed_memory(admin_conn, tenant, "a deleted fact about acme", status="deleted")
    with admin_conn.cursor() as cur:
        cur.execute(
            "INSERT INTO memory_entity (memory_id, tenant_id, entity) VALUES (%s, %s, 'acme')",
            (memory_id, tenant),
        )
    admin_conn.commit()

    with job_connection() as conn:
        with conn.cursor() as cur:
            run_purge_job(cur)

    with admin_conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM memory_entity WHERE memory_id = %s", (memory_id,))
        assert cur.fetchone()[0] == 0, "the search index side must be cleaned up along with the row"


# ── the DELETE endpoint (design/api_contracts.md `DELETE /v1/memories/{id}`) ─

def test_delete_endpoint_marks_deleted_and_disappears_from_reads_instantly(client, admin_conn, two_tenants):
    tenant = two_tenants["a"]
    memory_id = _seed_memory(admin_conn, tenant, "a fact the user wants gone")

    token = mint_token(tenant)
    resp = client.delete(f"/v1/memories/{memory_id}", headers={"Authorization": f"Bearer {token}"})

    assert resp.status_code == 200
    assert resp.json() == {"id": memory_id, "status": "deleted", "purge_within_seconds": 60}

    listed = client.get("/v1/memories", headers={"Authorization": f"Bearer {token}"})
    assert memory_id not in [m["id"] for m in listed.json()], "gone from reads instantly (INV-4)"

    with admin_conn.cursor() as cur:
        cur.execute("SELECT status FROM memory WHERE id = %s", (memory_id,))
        assert cur.fetchone()[0] == "deleted", "row still physically present until the purge job runs"


def test_delete_endpoint_on_unknown_or_cross_tenant_id_returns_404(client, admin_conn, two_tenants):
    memory_id = _seed_memory(admin_conn, two_tenants["a"], "tenant a's fact")

    token = mint_token(two_tenants["b"])
    resp = client.delete(f"/v1/memories/{memory_id}", headers={"Authorization": f"Bearer {token}"})

    assert resp.status_code == 404


def test_delete_endpoint_is_idempotent_on_an_already_deleted_memory(client, admin_conn, two_tenants):
    tenant = two_tenants["a"]
    memory_id = _seed_memory(admin_conn, tenant, "already deleted", status="deleted")

    token = mint_token(tenant)
    resp = client.delete(f"/v1/memories/{memory_id}", headers={"Authorization": f"Bearer {token}"})

    assert resp.status_code == 200
    assert resp.json() == {"id": memory_id, "status": "deleted", "purge_within_seconds": 60}
    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM audit_log WHERE tenant_id = %s AND action = 'deleted' AND memory_id = %s",
            (tenant, memory_id),
        )
        assert cur.fetchone()[0] == 0, "an already-deleted memory must not be re-audited"


def test_delete_then_purge_makes_it_physically_gone_within_the_stated_window(client, admin_conn, two_tenants):
    """End-to-end INV-4 demo: the two-step order from data_model.md, exercised
    through the real HTTP contract plus the real job function, no sleep."""
    tenant = two_tenants["a"]
    memory_id = _seed_memory(admin_conn, tenant, "a fact the user wants fully gone")

    token = mint_token(tenant)
    resp = client.delete(f"/v1/memories/{memory_id}", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200

    with job_connection() as conn:
        with conn.cursor() as cur:
            result = run_purge_job(cur)

    assert memory_id in result.purged_ids
    with admin_conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM memory WHERE id = %s", (memory_id,))
        assert cur.fetchone()[0] == 0


# ── retrieval "tops up" usefulness on a successful read (C9) ───────────────

def test_hybrid_search_bumps_access_count_and_last_accessed_on_the_memories_it_returns(
    admin_conn, two_tenants
):
    from retrieval.indexer import index_memory
    from retrieval.search import hybrid_search
    from tests.conftest import FakeEmbedder

    tenant = two_tenants["a"]
    concept = [1.0] + [0.0] * 1535
    embedder = FakeEmbedder({"the postgresql version in use": concept, "query about postgresql": concept})
    with admin_conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO memory (tenant_id, type, content, importance, confidence)
            VALUES (%s, 'fact', %s, 5, 0.9)
            RETURNING id
            """,
            (tenant, "the postgresql version in use"),
        )
        memory_id = cur.fetchone()[0]
        index_memory(cur, memory_id, tenant, "the postgresql version in use", embedder)
    admin_conn.commit()

    from db.connection import tenant_connection

    with tenant_connection(tenant) as conn:
        with conn.cursor() as cur:
            result = hybrid_search(cur, "query about postgresql", embedder)

    assert not result.abstained
    assert str(memory_id) in [m.id for m in result.memories]
    with admin_conn.cursor() as cur:
        cur.execute("SELECT access_count, last_accessed_at FROM memory WHERE id = %s", (memory_id,))
        access_count, last_accessed_at = cur.fetchone()
    assert access_count == 1
    assert last_accessed_at is not None
