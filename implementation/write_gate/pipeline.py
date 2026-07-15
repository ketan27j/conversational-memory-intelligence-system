"""Orchestrates extraction -> write-gate judging -> store/reject, all logged
to audit_log so decisions become training data later (first_principles.md C3).

Runs in the background (ADR-005) — the secrets check that gates whether we
even get here runs synchronously in api/main.py, before this is queued.
"""
from extraction.extractor import AnthropicFactExtractor, FactExtractor
from write_gate.judge import AnthropicWriteGateJudge, WriteGateJudge
from db.connection import tenant_connection


def get_extractor() -> FactExtractor:
    return AnthropicFactExtractor()


def get_judge() -> WriteGateJudge:
    return AnthropicWriteGateJudge()


def process_turn(
    tenant_id: str,
    turn_id: str,
    text: str,
    extractor: FactExtractor,
    judge: WriteGateJudge,
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
                    memory_id = cur.fetchone()[0]
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
