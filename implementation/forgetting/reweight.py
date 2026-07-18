"""Nightly C9 weight recalculation + archiving (first_principles.md C9):
"weight = importance x recency x how often it has been useful ... A nightly
background job (never on the live request path) reduces the weights and
archives anything below a floor. Archived, not deleted."

Recomputes `weight` fresh each run from the memory's current importance,
staleness since it was last actually useful (`last_accessed_at`, falling
back to `created_at` if it has never been retrieved), and how often it has
been useful (`access_count`) — rather than decaying a stored running total —
so the result depends only on the memory's present state, never on how many
times this job has previously fired.

Deliberately its own constants, not shared with retrieval/search.py's C6
ranking formula: C6 ranks by recency-since-created (a "how fresh is this"
signal) and C9 forgets by recency-since-last-useful (a "has anyone needed
this lately" signal) — same shape of decay curve, different reference
timestamp and different purpose, so keeping them separate avoids risking an
accidental behavior change to M2's already-verified ranking code.
"""
import math
from dataclasses import dataclass
from datetime import datetime, timezone

from psycopg import Cursor

# Half-life for staleness decay: an unused memory's recency term halves every
# this many days since it was last actually useful. Starting guess, tunable
# like every other ADR-002-precedent constant in this codebase.
STALENESS_HALF_LIFE_DAYS = 30.0

# Below this weight, an active memory is archived.
ARCHIVE_FLOOR = 0.05


@dataclass(frozen=True)
class ReweightResult:
    evaluated: int
    archived_ids: list[str]


def _recency(reference: datetime, now: datetime) -> float:
    age_days = max(0.0, (now - reference).total_seconds() / 86400.0)
    return math.pow(0.5, age_days / STALENESS_HALF_LIFE_DAYS)


def _usefulness(access_count: int) -> float:
    """1.0 baseline, not 0 — a brand-new, never-yet-retrieved memory must
    not be archived on the very first job run after it's written. Access
    history is a bonus multiplier on top of "assumed useful," not a
    requirement, diminishing returns bounded under 2.0."""
    return 1.0 + access_count / (access_count + 5.0)


def run_reweight_job(cur: Cursor, now: datetime | None = None) -> ReweightResult:
    """Cross-tenant by design — `cur` must come from `db.connection.job_connection()`
    (BYPASSRLS), never `tenant_connection()`. Evaluates every active memory
    across every tenant in one pass."""
    now = now or datetime.now(timezone.utc)
    cur.execute(
        """
        SELECT id, tenant_id, importance, access_count, last_accessed_at, created_at
        FROM memory
        WHERE status = 'active'
        """
    )
    rows = cur.fetchall()
    archived_ids: list[str] = []
    for mem_id, tenant_id, importance, access_count, last_accessed_at, created_at in rows:
        reference = last_accessed_at or created_at
        weight = (importance / 10.0) * _recency(reference, now) * _usefulness(access_count)
        if weight < ARCHIVE_FLOOR:
            cur.execute(
                "UPDATE memory SET status = 'archived', weight = %s, updated_at = now() WHERE id = %s",
                (weight, mem_id),
            )
            cur.execute(
                """
                INSERT INTO audit_log (tenant_id, actor, action, memory_id, detail)
                VALUES (%s, 'forgetting_job', 'archived', %s, %s)
                """,
                (tenant_id, mem_id, f"weight {weight:.4f} below floor {ARCHIVE_FLOOR}"),
            )
            archived_ids.append(str(mem_id))
        else:
            cur.execute(
                "UPDATE memory SET weight = %s, updated_at = now() WHERE id = %s",
                (weight, mem_id),
            )
    return ReweightResult(evaluated=len(rows), archived_ids=archived_ids)
