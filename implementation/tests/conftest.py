import hashlib
import random
import time
import uuid
from pathlib import Path

import psycopg
import pytest

from retrieval.embedder import EMBEDDING_DIM

ADMIN_DSN = "postgresql://cmis:cmis_dev_only@localhost:5433/cmis"
SCHEMA_SQL = Path(__file__).parent.parent / "db" / "schema.sql"


@pytest.fixture(scope="session", autouse=True)
def wait_for_postgres():
    """M0's tests need the isolated docker-compose stack running:
    `docker compose -f implementation/docker-compose.yml up -d`

    Docker Desktop's file-sharing restrictions block bind-mounting schema.sql
    into docker-entrypoint-initdb.d on this host, so the schema is applied
    here instead (idempotent: only runs if `memory` doesn't exist yet).
    """
    last_err = None
    conn = None
    for _ in range(30):
        try:
            conn = psycopg.connect(ADMIN_DSN, connect_timeout=1)
            break
        except Exception as e:
            last_err = e
            time.sleep(1)
    if conn is None:
        pytest.fail(
            f"postgres at {ADMIN_DSN} not reachable after 30s — "
            f"run `docker compose -f implementation/docker-compose.yml up -d` first. "
            f"Last error: {last_err}"
        )

    with conn.cursor() as cur:
        cur.execute(
            "SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'memory')"
        )
        schema_applied = cur.fetchone()[0]
    if not schema_applied:
        conn.execute(SCHEMA_SQL.read_text())
        conn.commit()
    conn.close()


@pytest.fixture
def admin_conn():
    """Superuser connection — bypasses RLS. Used only to set up cross-tenant
    fixtures and to independently verify data exists, never by app code."""
    conn = psycopg.connect(ADMIN_DSN)
    yield conn
    conn.rollback()
    conn.close()


@pytest.fixture
def two_tenants():
    return {"a": str(uuid.uuid4()), "b": str(uuid.uuid4())}


class FakeExtractor:
    """Deterministic stand-in for AnthropicFactExtractor (C14: repeatable
    testing — tests must not depend on a live LLM call)."""

    def __init__(self, facts: list[str] | None = None):
        self.facts = facts if facts is not None else []

    def extract(self, text: str) -> list[str]:
        return self.facts


class FakeJudge:
    """Deterministic stand-in for AnthropicWriteGateJudge."""

    def __init__(self, decision_fn):
        self.decision_fn = decision_fn

    def judge(self, candidate: str):
        return self.decision_fn(candidate)


class FakeEmbedder:
    """Deterministic stand-in for VoyageEmbedder (C14: repeatable testing —
    must not depend on a live embedding API call).

    Tests that need to control *similarity* (e.g. "these two sentences are
    semantically related despite sharing no words") pass an explicit
    text->vector map; give both texts the identical vector to force
    similarity 1.0. Any text not in the map gets a stable hash-derived
    vector so unrelated texts land far apart (near-orthogonal, as real
    embeddings would for unrelated content) without colliding with the
    explicit ones.
    """

    def __init__(self, vectors: dict[str, list[float]] | None = None):
        self.vectors = vectors or {}

    def embed(self, text: str) -> list[float]:
        if text in self.vectors:
            return self.vectors[text]
        seed = int.from_bytes(hashlib.sha256(text.encode()).digest()[:8], "big")
        rng = random.Random(seed)
        return [rng.uniform(-1, 1) for _ in range(EMBEDDING_DIM)]


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    from api.main import app
    from write_gate.pipeline import get_embedder, get_extractor, get_judge
    from write_gate.judge import Decision

    # Safe defaults: extract nothing, reject anything unexpected. Individual
    # tests override further via app.dependency_overrides as needed.
    app.dependency_overrides[get_extractor] = lambda: FakeExtractor([])
    app.dependency_overrides[get_judge] = lambda: FakeJudge(
        lambda candidate: Decision(keep=False, importance=1, confidence=0.0, reason="unexpected candidate in test")
    )
    app.dependency_overrides[get_embedder] = lambda: FakeEmbedder()
    yield TestClient(app)
    app.dependency_overrides.clear()
