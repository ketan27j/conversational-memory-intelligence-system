"""Orchestrates extraction -> write-gate judging -> store/reject, all logged
to audit_log so decisions become training data later (first_principles.md C3).

Runs in the background (ADR-005) — the secrets check that gates whether we
even get here runs synchronously in api/main.py, before this is queued.

M2 addition (checkpoints/M2.md G0): a kept memory is also indexed —
embedding + entity rows populated — via retrieval/indexer.py, right after
the INSERT, in the same cursor/transaction. This is the one required touch
outside M2's declared freeze boundary (`implementation/retrieval/**`):
without it, hybrid search would only ever see hand-seeded test fixtures,
never a real write. Same "necessary alignment, not scope creep" precedent
M1 used when it touched api/main.py for the M0-declared endpoints.
"""
from extraction.extractor import AnthropicFactExtractor, FactExtractor
from retrieval.embedder import Embedder, VoyageEmbedder
from retrieval.indexer import index_memory
from write_gate.judge import AnthropicWriteGateJudge, WriteGateJudge
from db.connection import tenant_connection


def get_extractor() -> FactExtractor:
    return AnthropicFactExtractor()


def get_judge() -> WriteGateJudge:
    return AnthropicWriteGateJudge()


def get_embedder() -> Embedder:
    return VoyageEmbedder()


def process_turn(
    tenant_id: str,
    turn_id: str,
    text: str,
    extractor: FactExtractor,
    judge: WriteGateJudge,
    embedder: Embedder,
) -> None:
    candidates = extractor.extract(text)

    with tenant_connection(tenant_id) as conn:
        for candidate in candidates:
            decision = judge.judge(candidate)
            with conn.cursor() as cur:
                if decision.keep:
                    cur.execute(
                        """
                        INSERT INTO memory
                            (tenant_id, type, content, importance, confidence, source_turn_id)
                        VALUES (%s, 'fact', %s, %s, %s, %s)
                        RETURNING id
                        """,
                        (tenant_id, candidate, decision.importance, decision.confidence, turn_id),
                    )
                    row = cur.fetchone()
                    assert row is not None
                    memory_id = row[0]
                    index_memory(cur, memory_id, tenant_id, candidate, embedder)
                    cur.execute(
                        """
                        INSERT INTO audit_log (tenant_id, actor, action, memory_id, detail)
                        VALUES (%s, 'write_gate', 'stored', %s, %s)
                        """,
                        (tenant_id, memory_id, decision.reason),
                    )
                else:
                    cur.execute(
                        """
                        INSERT INTO audit_log (tenant_id, actor, action, detail)
                        VALUES (%s, 'write_gate', 'rejected', %s)
                        """,
                        (tenant_id, decision.reason),
                    )
