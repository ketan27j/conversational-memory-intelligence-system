"""The four health numbers (first_principles.md C12): is memory being used,
is it right, how fast is it, what does it cost. Computed from `audit_log`
(usage/correction — decisions already logged since M1/M3) and the new M5
`request_metric` table (latency/cost — nothing wrote these before this
milestone).

Runs on a tenant-scoped cursor (same RLS-does-the-filtering pattern as
retrieval/search.py) — the dashboard is per-tenant, consistent with the rest
of this codebase's security model (no BYPASSRLS role is ever exposed over
HTTP, per M0's hardening note).
"""
from dataclasses import dataclass

from psycopg import Cursor

# Pricing estimates, not billing-verified — same "documented approximation"
# posture as experiments/baseline_protocol.md's "~1.3 tokens/word" note.
# Claude Haiku 4.5 (AnthropicFactExtractor + AnthropicWriteGateJudge):
# $1.00 / $5.00 per 1M input/output tokens, per the claude-api skill's
# pricing table (checked live before writing this, since this module
# assigns a dollar cost to Anthropic model calls).
_HAIKU_INPUT_USD_PER_TOKEN = 1.00 / 1_000_000
_HAIKU_OUTPUT_USD_PER_TOKEN = 5.00 / 1_000_000
# Voyage voyage-3-lite (retrieval/embedder.py): no Anthropic pricing source
# applies (non-Anthropic vendor) — placeholder at Voyage's public list price,
# flagged here as an estimate rather than a verified figure.
_VOYAGE_USD_PER_TOKEN = 0.02 / 1_000_000
# chars/4 ~ tokens, the same order-of-magnitude approximation the baseline
# protocol uses (~1.3 tokens/word ~ 1 token per 4-5 chars for English text).
_CHARS_PER_TOKEN = 4.0


def estimate_llm_cost_usd(input_chars: int, output_chars: int) -> float:
    """Approximate cost of one Haiku call from prompt/response length. Used
    in place of capturing real `usage.input_tokens`/`usage.output_tokens`
    because that would require changing AnthropicFactExtractor/
    AnthropicWriteGateJudge's call sites and Decision's return shape —
    out of this milestone's freeze boundary, and those call sites are
    already covered by FakeExtractor/FakeJudge in tests (C14), so this
    estimate is length-based rather than plumbed through a live response."""
    input_tokens = input_chars / _CHARS_PER_TOKEN
    output_tokens = output_chars / _CHARS_PER_TOKEN
    return input_tokens * _HAIKU_INPUT_USD_PER_TOKEN + output_tokens * _HAIKU_OUTPUT_USD_PER_TOKEN


def estimate_embedding_cost_usd(chars: int) -> float:
    """Approximate cost of one Voyage embedding call from input length."""
    return (chars / _CHARS_PER_TOKEN) * _VOYAGE_USD_PER_TOKEN


def record_metric(cur: Cursor, tenant_id: str, endpoint: str, latency_ms: float, cost_usd: float = 0.0) -> None:
    cur.execute(
        """
        INSERT INTO request_metric (tenant_id, endpoint, latency_ms, cost_usd)
        VALUES (%s, %s, %s, %s)
        """,
        (tenant_id, endpoint, latency_ms, cost_usd),
    )


@dataclass(frozen=True)
class HealthSnapshot:
    usage_rate: float  # retrievals per memory stored (audit_log 'retrieved' / 'stored')
    correction_rate: float  # corrections per memory stored (audit_log 'replaced' / 'stored')
    latency_p50_ms: float
    latency_p95_ms: float
    cost_per_write_usd: float
    cost_per_retrieval_usd: float
    stored_count: int
    retrieved_count: int
    corrected_count: int


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = min(len(ordered) - 1, max(0, round(pct * (len(ordered) - 1))))
    return ordered[idx]


def compute_health(cur: Cursor) -> HealthSnapshot:
    cur.execute(
        """
        SELECT action, COUNT(*) FROM audit_log
        WHERE action IN ('stored', 'retrieved', 'replaced')
        GROUP BY action
        """
    )
    counts = {row[0]: row[1] for row in cur.fetchall()}
    stored = counts.get("stored", 0)
    retrieved = counts.get("retrieved", 0)
    corrected = counts.get("replaced", 0)

    cur.execute("SELECT latency_ms, cost_usd, endpoint FROM request_metric")
    rows = cur.fetchall()
    retrieve_latencies = [r[0] for r in rows if r[2] == "retrieve"]
    write_costs = [r[1] for r in rows if r[2] == "ingest"]
    retrieve_costs = [r[1] for r in rows if r[2] == "retrieve"]

    return HealthSnapshot(
        usage_rate=(retrieved / stored) if stored else 0.0,
        correction_rate=(corrected / stored) if stored else 0.0,
        latency_p50_ms=_percentile(retrieve_latencies, 0.50),
        latency_p95_ms=_percentile(retrieve_latencies, 0.95),
        cost_per_write_usd=(sum(write_costs) / len(write_costs)) if write_costs else 0.0,
        cost_per_retrieval_usd=(sum(retrieve_costs) / len(retrieve_costs)) if retrieve_costs else 0.0,
        stored_count=stored,
        retrieved_count=retrieved,
        corrected_count=corrected,
    )
