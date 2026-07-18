"""API surface per design/api_contracts.md.

M0 shipped a placeholder skeleton (`POST /messages`); M1 replaces it with the
documented `/v1/memories:ingest` contract, since M1 is what actually builds
the secrets-check-then-background-queue behavior (ADR-005) this contract
describes. M2 adds `POST /v1/memories:retrieve` (hybrid search + ranking +
relevance-bar abstention) — the other required touch outside M2's declared
freeze boundary, since api_contracts.md's retrieve contract is what this
milestone's outcome is documented against. M3 adds `POST /v1/memories:feedback`
— the user-facing "that's wrong"/"that's out of date" correction endpoint
`design/api_contracts.md` documents for this milestone. M4 adds
`DELETE /v1/memories/{id}` — required outside M4's declared freeze boundary
(`implementation/forgetting/**` + `implementation/jobs/**`) since INV-4
("gone from reads instantly") can only be demonstrated through the real HTTP
contract, same "necessary alignment, not scope creep" precedent as M1-M3.
M5 adds latency/audit/cost instrumentation to `retrieve()` and
`GET /v1/observability/health` (checkpoints/M5.md) — required outside M5's
declared freeze boundary (`implementation/observability/**` +
`implementation/benchmark.py`) since C12's health numbers must be computed
from real per-request data, not fixtures, and C13/INV-7 graceful degradation
("the lookup times out and the assistant answers without memory") can only
be demonstrated through the real HTTP contract's `503 memory_unavailable`.
"""
import time
import uuid
from typing import Literal

import psycopg
from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException
from pydantic import BaseModel, Field

from api.auth import verify_token
from db.connection import tenant_connection
from extraction.extractor import FactExtractor
from observability.metrics import HealthSnapshot, compute_health, estimate_embedding_cost_usd, record_metric
from prototypes.reranker import Reranker, get_reranker
from retrieval.embedder import Embedder
from retrieval.search import hybrid_search
from secrets_filter import detector
from write_gate.judge import WriteGateJudge
from write_gate.pipeline import get_embedder, get_extractor, get_judge, process_turn

app = FastAPI(title="Conversational Memory Intelligence System")


class MessageIn(BaseModel):
    session_id: uuid.UUID
    role: Literal["user", "assistant"]
    text: str = Field(min_length=1, max_length=8000)


class IngestOut(BaseModel):
    turn_id: uuid.UUID
    status: Literal["queued"]
    pii_blocked: bool


class MemoryOut(BaseModel):
    id: uuid.UUID
    type: str
    content: str
    importance: int
    confidence: float


class RetrieveIn(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    token_budget: int = Field(default=512, gt=0)
    k_max: int = Field(default=8, gt=0)
    rerank: bool = False  # ADR-006: reranker is a switch for M6 — accepted, not implemented, here


class ScoredMemoryOut(BaseModel):
    id: uuid.UUID
    type: str
    content: str
    score: float
    importance: int
    confidence: float
    created_at: str


class RetrieveOut(BaseModel):
    memories: list[ScoredMemoryOut]
    abstained: bool
    tokens_used: int
    signals: dict[str, float]


class FeedbackIn(BaseModel):
    memory_id: uuid.UUID
    signal: Literal["outdated"]


class FeedbackOut(BaseModel):
    superseded: bool
    new_status: str


class DeleteOut(BaseModel):
    id: uuid.UUID
    status: Literal["deleted"]
    purge_within_seconds: int


@app.post("/v1/memories:ingest", response_model=IngestOut, status_code=201)
def ingest(
    msg: MessageIn,
    background_tasks: BackgroundTasks,
    tenant_id: str = Depends(verify_token),
    extractor: FactExtractor = Depends(get_extractor),
    judge: WriteGateJudge = Depends(get_judge),
    embedder: Embedder = Depends(get_embedder),
) -> IngestOut:
    """Per ADR-005: the secrets check runs right now, before anything is
    queued. Extraction and the write gate run in the background."""
    findings = detector.scan(msg.text)
    pii_blocked = bool(findings)

    if pii_blocked and detector.is_entirely_secret(msg.text, findings):
        with tenant_connection(tenant_id) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO audit_log (tenant_id, actor, action, detail)
                    VALUES (%s, 'secrets_filter', 'blocked_secret', 'entire message was a secret')
                    """,
                    (tenant_id,),
                )
        raise HTTPException(status_code=422, detail="pii_rejected")

    stored_text = detector.redact(msg.text, findings) if findings else msg.text

    with tenant_connection(tenant_id) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO conversation_turn (tenant_id, session_id, role, text)
                VALUES (%s, %s, %s, %s)
                RETURNING id
                """,
                (tenant_id, str(msg.session_id), msg.role, stored_text),
            )
            row = cur.fetchone()
            assert row is not None
            turn_id = row[0]
            if pii_blocked:
                cur.execute(
                    """
                    INSERT INTO audit_log (tenant_id, actor, action, detail)
                    VALUES (%s, 'secrets_filter', 'blocked_secret', %s)
                    """,
                    (tenant_id, f"{len(findings)} secret(s) redacted from turn {turn_id}"),
                )

    background_tasks.add_task(
        process_turn, tenant_id, str(turn_id), stored_text, extractor, judge, embedder
    )

    return IngestOut(turn_id=turn_id, status="queued", pii_blocked=pii_blocked)


@app.get("/v1/memories", response_model=list[MemoryOut])
def list_memories(tenant_id: str = Depends(verify_token)) -> list[MemoryOut]:
    """List this tenant's active memories — inspection/dashboard use, not the
    answer-time retrieval path (that's POST /v1/memories:retrieve below)."""
    with tenant_connection(tenant_id) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, type, content, importance, confidence
                FROM memory
                WHERE status = 'active'
                ORDER BY created_at DESC
                """
            )
            rows = cur.fetchall()
    return [
        MemoryOut(id=r[0], type=r[1], content=r[2], importance=r[3], confidence=r[4])
        for r in rows
    ]


@app.post("/v1/memories:retrieve", response_model=RetrieveOut)
def retrieve(
    body: RetrieveIn,
    tenant_id: str = Depends(verify_token),
    embedder: Embedder = Depends(get_embedder),
    reranker: Reranker = Depends(get_reranker),
) -> RetrieveOut:
    """Hybrid search (vector + keyword + entity) + C6 ranking + INV-6
    relevance-bar abstention. `rerank` (M6, ADR-006, checkpoints/M6.md) now
    does something real: a second-pass rescore of the returned candidates,
    run after the DB transaction closes (the reranker needs no DB access,
    so there's no reason to hold the connection open across what may be
    several LLM round trips). Off by default (`rerank: bool = False`) and
    stays off in production regardless of `prototypes/rerank_experiment.py`'s
    verdict — ADR-006 requires the switch to ship off; this only makes the
    already-accepted switch real instead of inert. Skipped entirely when the
    search abstained or returned nothing — there's nothing to rescore.

    C13/INV-7 (api_contracts.md): "the lookup times out and the assistant
    answers without memory". `tenant_connection`'s `connect_timeout` (M5,
    db/connection.py) bounds how long a down/unreachable database can hang
    this call; either that timeout or any other connection failure is
    reported as 503 `memory_unavailable` rather than a 500 or a hang, so the
    caller can answer the turn without memory instead of failing it."""
    start = time.monotonic()
    try:
        with tenant_connection(tenant_id) as conn:
            with conn.cursor() as cur:
                result = hybrid_search(
                    cur, body.query, embedder, k_max=body.k_max, token_budget=body.token_budget
                )
                latency_ms = (time.monotonic() - start) * 1000
                cur.execute(
                    """
                    INSERT INTO audit_log (tenant_id, actor, action, detail)
                    VALUES (%s, 'retrieval', 'retrieved', %s)
                    """,
                    (tenant_id, f"{len(result.memories)} memories, abstained={result.abstained}"),
                )
                record_metric(
                    cur, tenant_id, "retrieve", latency_ms,
                    estimate_embedding_cost_usd(len(body.query)),
                )
    except psycopg.OperationalError:
        raise HTTPException(status_code=503, detail="memory_unavailable")

    memories = result.memories
    if body.rerank and not result.abstained and memories:
        memories = reranker.rerank(body.query, memories)

    return RetrieveOut(
        memories=[
            ScoredMemoryOut(
                id=uuid.UUID(m.id),
                type=m.type,
                content=m.content,
                score=m.score,
                importance=m.importance,
                confidence=m.confidence,
                created_at=m.created_at.isoformat(),
            )
            for m in memories
        ],
        abstained=result.abstained,
        tokens_used=result.tokens_used,
        signals=result.signals,
    )


@app.post("/v1/memories:feedback", response_model=FeedbackOut)
def feedback(body: FeedbackIn, tenant_id: str = Depends(verify_token)) -> FeedbackOut:
    """"That's wrong" / "that's out of date" (design/api_contracts.md): flips
    the memory straight to `superseded`, no replacement memory required. RLS
    (via tenant_connection) means a memory_id belonging to another tenant is
    indistinguishable from one that doesn't exist — 404 either way, never a
    cross-tenant leak. A memory that isn't `active` (already superseded,
    archived, or deleted) is left as-is and its current status is reported
    back rather than silently overwritten."""
    with tenant_connection(tenant_id) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT status FROM memory WHERE id = %s", (str(body.memory_id),))
            row = cur.fetchone()
            if row is None:
                raise HTTPException(status_code=404, detail="memory_not_found")
            current_status = row[0]
            if current_status != "active":
                return FeedbackOut(
                    superseded=(current_status == "superseded"), new_status=current_status
                )

            cur.execute(
                "UPDATE memory SET status = 'superseded', updated_at = now() WHERE id = %s",
                (str(body.memory_id),),
            )
            cur.execute(
                """
                INSERT INTO audit_log (tenant_id, actor, action, memory_id, detail)
                VALUES (%s, 'user_feedback', 'replaced', %s, %s)
                """,
                (tenant_id, str(body.memory_id), f"signal={body.signal}"),
            )
    return FeedbackOut(superseded=True, new_status="superseded")


# INV-4 (context-graph.json): the promised window between "marked deleted"
# and "physically purged" (implementation/forgetting/purge.py finishes the
# second half, on a short interval — see implementation/jobs/purge_deleted.py).
PURGE_WINDOW_SECONDS = 60


@app.delete("/v1/memories/{memory_id}", response_model=DeleteOut)
def delete_memory(memory_id: uuid.UUID, tenant_id: str = Depends(verify_token)) -> DeleteOut:
    """Right to be forgotten (design/api_contracts.md, C11, INV-4). Marks the
    memory deleted immediately — from this instant no read returns it — and
    leaves the physical row removal to `forgetting.purge.run_purge_job`
    within `purge_within_seconds` (data_model.md's two-step order: invisible
    first, physically gone second). Unknown/cross-tenant id -> 404 (RLS makes
    the two indistinguishable, same reasoning as the feedback endpoint).
    Already-deleted -> 200 idempotent, no re-audit. Any other status
    (archived/superseded) is still a valid delete target — the right to be
    forgotten applies regardless of a memory's current lifecycle stage."""
    with tenant_connection(tenant_id) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT status FROM memory WHERE id = %s", (str(memory_id),))
            row = cur.fetchone()
            if row is None:
                raise HTTPException(status_code=404, detail="memory_not_found")
            if row[0] == "deleted":
                return DeleteOut(
                    id=memory_id, status="deleted", purge_within_seconds=PURGE_WINDOW_SECONDS
                )

            cur.execute(
                "UPDATE memory SET status = 'deleted', updated_at = now() WHERE id = %s",
                (str(memory_id),),
            )
            cur.execute(
                """
                INSERT INTO audit_log (tenant_id, actor, action, memory_id, detail)
                VALUES (%s, 'user_request', 'deleted', %s, 'marked deleted, pending purge')
                """,
                (tenant_id, str(memory_id)),
            )
    return DeleteOut(id=memory_id, status="deleted", purge_within_seconds=PURGE_WINDOW_SECONDS)


@app.get("/v1/observability/health", response_model=HealthSnapshot)
def health(tenant_id: str = Depends(verify_token)) -> HealthSnapshot:
    """C12 (first_principles.md): the four health numbers — usage rate,
    correction rate, latency, cost — for this tenant. Tenant-scoped like
    `GET /v1/memories` (same "inspection/dashboard, not the live request
    path" role, same reasoning as that endpoint's own docstring): no
    BYPASSRLS role is exposed on any HTTP endpoint (M0's hardening note),
    so a cross-tenant aggregate dashboard is not offered here."""
    with tenant_connection(tenant_id) as conn:
        with conn.cursor() as cur:
            return compute_health(cur)
