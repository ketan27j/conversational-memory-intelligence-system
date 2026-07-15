"""API surface per design/api_contracts.md.

M0 shipped a placeholder skeleton (`POST /messages`); M1 replaces it with the
documented `/v1/memories:ingest` contract, since M1 is what actually builds
the secrets-check-then-background-queue behavior (ADR-005) this contract
describes. Ranking/hybrid search for GET /v1/memories is still M2.
"""
import uuid
from typing import Literal

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException
from pydantic import BaseModel, Field

from api.auth import verify_token
from db.connection import tenant_connection
from extraction.extractor import FactExtractor
from secrets_filter import detector
from write_gate.judge import WriteGateJudge
from write_gate.pipeline import get_extractor, get_judge, process_turn

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


@app.post("/v1/memories:ingest", response_model=IngestOut, status_code=201)
def ingest(
    msg: MessageIn,
    background_tasks: BackgroundTasks,
    tenant_id: str = Depends(verify_token),
    extractor: FactExtractor = Depends(get_extractor),
    judge: WriteGateJudge = Depends(get_judge),
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
            turn_id = cur.fetchone()[0]
            if pii_blocked:
                cur.execute(
                    """
                    INSERT INTO audit_log (tenant_id, actor, action, detail)
                    VALUES (%s, 'secrets_filter', 'blocked_secret', %s)
                    """,
                    (tenant_id, f"{len(findings)} secret(s) redacted from turn {turn_id}"),
                )

    background_tasks.add_task(process_turn, tenant_id, str(turn_id), stored_text, extractor, judge)

    return IngestOut(turn_id=turn_id, status="queued", pii_blocked=pii_blocked)


@app.get("/v1/memories", response_model=list[MemoryOut])
def list_memories(tenant_id: str = Depends(verify_token)) -> list[MemoryOut]:
    """List this tenant's active memories. Ranking/hybrid search: M2."""
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
