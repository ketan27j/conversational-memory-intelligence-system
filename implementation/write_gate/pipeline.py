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

M3 addition (checkpoints/M3.md): right after indexing, check the newly
stored memory against existing active memories on the same subject
(contradiction/detector.py) and resolve who wins (contradiction/resolver.py,
C8) — in the same cursor/transaction, so a kept memory's contradiction with
history is settled before this function returns.

M5 addition (checkpoints/M5.md): one `request_metric` row per turn, costing
the extraction + write-gate judge calls this function already made — the
only place that has both the input `text` and every `candidate` in hand
without adding a new touch to extraction/extractor.py or write_gate/judge.py
(out of M5's declared freeze boundary, and both already have FakeExtractor/
FakeJudge test doubles per C14 that a return-shape change would need to
follow). Cost is a length-based estimate (observability/metrics.py), not a
captured `usage.input_tokens`/`output_tokens`, for the same reason.

M6 addition (checkpoints/M6.md, G0 gap): one `write_gate_decision` row per
judge call, both branches — this docstring (and ADR-001) have claimed since
M1 that "every decision is logged so it can become training data," but the
reject branch never actually stored the candidate's text anywhere, only
`decision.reason`. Without this, M6's write-gate-classifier prototype would
have nothing real to train on.
"""
import time

from psycopg import Cursor

from contradiction.detector import find_same_subject
from contradiction.resolver import resolve_contradictions
from extraction.extractor import AnthropicFactExtractor, FactExtractor
from observability.metrics import estimate_llm_cost_usd, record_metric
from retrieval.embedder import Embedder, VoyageEmbedder
from retrieval.indexer import index_memory
from write_gate.judge import AnthropicWriteGateJudge, Decision, WriteGateJudge
from db.connection import tenant_connection


def _record_decision(cur: Cursor, tenant_id: str, candidate: str, decision: Decision) -> None:
    cur.execute(
        """
        INSERT INTO write_gate_decision
            (tenant_id, candidate_text, kept, importance, confidence, reason)
        VALUES (%s, %s, %s, %s, %s, %s)
        """,
        (tenant_id, candidate, decision.keep, decision.importance, decision.confidence, decision.reason),
    )


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
    start = time.monotonic()
    candidates = extractor.extract(text)
    # Judge output is a short JSON decision, not proportional to candidate
    # length — approximated at a fixed size rather than a per-candidate one.
    _JUDGE_OUTPUT_CHARS_ESTIMATE = 80
    cost_usd = estimate_llm_cost_usd(len(text), sum(len(c) for c in candidates))
    cost_usd += sum(
        estimate_llm_cost_usd(len(c), _JUDGE_OUTPUT_CHARS_ESTIMATE) for c in candidates
    )

    with tenant_connection(tenant_id) as conn:
        for candidate in candidates:
            decision = judge.judge(candidate)
            with conn.cursor() as cur:
                _record_decision(cur, tenant_id, candidate, decision)
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
                    same_subject = find_same_subject(cur, memory_id, "fact")
                    resolve_contradictions(cur, tenant_id, memory_id, decision.confidence, same_subject)
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
        latency_ms = (time.monotonic() - start) * 1000
        with conn.cursor() as cur:
            record_metric(cur, tenant_id, "ingest", latency_ms, cost_usd)
