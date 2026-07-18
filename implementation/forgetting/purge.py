"""Finishes pending deletions (first_principles.md C11, INV-4): a memory
marked `status='deleted'` (api/main.py's DELETE endpoint — step 1, instant,
already invisible to every read) gets physically removed from the database
here, within the stated 60-second window (step 2). The order matters
(data_model.md): even if this job runs late or crashes mid-batch, the memory
is already unreadable from the moment it was marked, so nobody can retrieve
something a user asked to delete.

`memory_entity` has `ON DELETE CASCADE` on `memory_id` (since M0), so the
entity/"search index" side is cleaned up by the database itself — no
separate index-purge code needed, consistent with ADR-003's one-Postgres-
database design.
"""
from dataclasses import dataclass

from psycopg import Cursor


@dataclass(frozen=True)
class PurgeResult:
    purged_ids: list[str]


def run_purge_job(cur: Cursor) -> PurgeResult:
    """Cross-tenant by design — same `job_connection()` (BYPASSRLS) as
    reweight.py. Hard-deletes every memory already marked `deleted`."""
    cur.execute("SELECT id, tenant_id FROM memory WHERE status = 'deleted'")
    rows = cur.fetchall()
    purged_ids: list[str] = []
    for mem_id, tenant_id in rows:
        cur.execute(
            """
            INSERT INTO audit_log (tenant_id, actor, action, memory_id, detail)
            VALUES (%s, 'forgetting_job', 'deleted', %s, 'purged from database')
            """,
            (tenant_id, mem_id),
        )
        cur.execute("DELETE FROM memory WHERE id = %s", (mem_id,))
        purged_ids.append(str(mem_id))
    return PurgeResult(purged_ids=purged_ids)
