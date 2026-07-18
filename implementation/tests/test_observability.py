"""M5 demo test. Success criteria (PLAN.md):
  - the four health numbers (usage rate, correction rate, latency, cost) are
    wired and computable from real per-request data, not fixtures
  - outage test: a memory store failure during retrieval never fails the
    turn — 503 `memory_unavailable`, fast, never a hang or a 500 (C13/INV-7)
"""
import time
import uuid

import db.connection as db_connection
from api.auth import mint_token
from db.connection import tenant_connection
from observability.metrics import (
    compute_health,
    estimate_embedding_cost_usd,
    estimate_llm_cost_usd,
    record_metric,
)
from write_gate.judge import Decision


def test_estimate_cost_scales_with_length():
    small = estimate_llm_cost_usd(10, 10)
    large = estimate_llm_cost_usd(1000, 1000)
    assert 0 < small < large
    assert estimate_embedding_cost_usd(0) == 0.0
    assert estimate_embedding_cost_usd(1000) > 0


def test_compute_health_from_seeded_audit_log_and_metrics(admin_conn, two_tenants):
    """Seeds via `admin_conn` (superuser, bypasses RLS — same pattern
    test_retrieval.py's `_seed_memory` uses) so an arbitrary tenant_id can be
    written directly, then reads back through a real `tenant_connection` so
    the assertion exercises the same RLS-scoped path `compute_health` runs
    on in production (a superuser session ignores `app.tenant_id` entirely,
    so reading through `admin_conn` would see every tenant's rows)."""
    tenant = two_tenants["a"]
    with admin_conn.cursor() as cur:
        for _ in range(4):
            cur.execute(
                "INSERT INTO audit_log (tenant_id, actor, action) VALUES (%s, 'write_gate', 'stored')",
                (tenant,),
            )
        for _ in range(2):
            cur.execute(
                "INSERT INTO audit_log (tenant_id, actor, action) VALUES (%s, 'retrieval', 'retrieved')",
                (tenant,),
            )
        cur.execute(
            "INSERT INTO audit_log (tenant_id, actor, action) VALUES (%s, 'user_feedback', 'replaced')",
            (tenant,),
        )
        for latency in [10.0, 20.0, 30.0, 100.0]:
            record_metric(cur, tenant, "retrieve", latency, cost_usd=0.001)
        record_metric(cur, tenant, "ingest", 50.0, cost_usd=0.002)
    admin_conn.commit()

    with tenant_connection(tenant) as conn:
        with conn.cursor() as cur:
            snapshot = compute_health(cur)

    assert snapshot.stored_count == 4
    assert snapshot.retrieved_count == 2
    assert snapshot.corrected_count == 1
    assert snapshot.usage_rate == 0.5  # 2 retrieved / 4 stored
    assert snapshot.correction_rate == 0.25  # 1 replaced / 4 stored
    assert snapshot.latency_p50_ms in (20.0, 30.0)  # median of [10,20,30,100]
    assert snapshot.latency_p95_ms == 100.0
    assert snapshot.cost_per_write_usd == 0.002
    assert snapshot.cost_per_retrieval_usd == 0.001


def test_compute_health_empty_tenant_has_zero_rates(two_tenants):
    tenant = two_tenants["b"]
    with tenant_connection(tenant) as conn:
        with conn.cursor() as cur:
            snapshot = compute_health(cur)
    assert snapshot.usage_rate == 0.0
    assert snapshot.correction_rate == 0.0
    assert snapshot.latency_p50_ms == 0.0
    assert snapshot.cost_per_write_usd == 0.0


def test_health_endpoint_reflects_full_write_retrieve_feedback_flow(client):
    tenant_id = str(uuid.uuid4())
    token = mint_token(tenant_id)

    from api.main import app
    from write_gate.pipeline import get_extractor, get_judge

    class OneFactExtractor:
        def extract(self, text):
            return ["uses PostgreSQL"]

    class KeepJudge:
        def judge(self, candidate):
            return Decision(keep=True, importance=5, confidence=0.9, reason="test")

    app.dependency_overrides[get_extractor] = lambda: OneFactExtractor()
    app.dependency_overrides[get_judge] = lambda: KeepJudge()
    try:
        ingest = client.post(
            "/v1/memories:ingest",
            json={"session_id": str(uuid.uuid4()), "role": "user", "text": "I use PostgreSQL."},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert ingest.status_code == 201

        retrieve = client.post(
            "/v1/memories:retrieve",
            json={"query": "what database"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert retrieve.status_code == 200

        health = client.get("/v1/observability/health", headers={"Authorization": f"Bearer {token}"})
        assert health.status_code == 200
        body = health.json()
        assert body["stored_count"] >= 1
        assert body["retrieved_count"] >= 1
        assert body["latency_p50_ms"] >= 0
        assert body["cost_per_retrieval_usd"] >= 0
    finally:
        app.dependency_overrides.pop(get_extractor, None)
        app.dependency_overrides.pop(get_judge, None)


def test_retrieve_returns_503_when_connection_refused(client, monkeypatch, two_tenants):
    """C13/INV-7: memory store failure never fails the turn — 503, not a
    hang or a 500. A refused local port fails near-instantly regardless of
    `connect_timeout` — see the blackhole-IP test below for the case that
    actually exercises the timeout bound."""
    tenant_id = two_tenants["a"]
    token = mint_token(tenant_id)
    monkeypatch.setattr(db_connection, "DSN", "postgresql://cmis_app:x@localhost:1/cmis")

    response = client.post(
        "/v1/memories:retrieve",
        json={"query": "anything"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 503
    assert response.json()["detail"] == "memory_unavailable"


def test_retrieve_returns_503_fast_when_store_unroutable(client, monkeypatch, two_tenants):
    """Unlike a refused port, an unroutable address (RFC 5737-style
    blackhole) doesn't fail instantly -- the OS default TCP connect timeout
    is minutes. This is the case that actually proves `connect_timeout`
    (db/connection.py, M5) bounds the wait rather than merely happening to
    return quickly."""
    tenant_id = two_tenants["a"]
    token = mint_token(tenant_id)
    monkeypatch.setattr(
        db_connection, "DSN", "postgresql://cmis_app:x@10.255.255.1:5433/cmis"
    )

    start = time.monotonic()
    response = client.post(
        "/v1/memories:retrieve",
        json={"query": "anything"},
        headers={"Authorization": f"Bearer {token}"},
    )
    elapsed = time.monotonic() - start

    assert response.status_code == 503
    assert response.json()["detail"] == "memory_unavailable"
    assert elapsed < db_connection.CONNECT_TIMEOUT_SECONDS + 5, (
        f"retrieve() took {elapsed:.1f}s -- connect_timeout isn't bounding the hang"
    )
