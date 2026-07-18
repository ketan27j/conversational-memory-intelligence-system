"""Decides who wins when a new memory turns out to be about the same subject
as an existing one (first_principles.md C8): "newer and more confident
usually wins... but always keep the old memory's history, so the change can
be audited. Sometimes both are true and both are kept."

Default rule applied here: the new memory supersedes a candidate only when it
is at least as confident as that candidate. When the new memory is *less*
confident, the candidate is left untouched — a single lower-confidence
extraction shouldn't overwrite a more settled, more-confident memory; both
stay active, exactly the "sometimes both are kept" case C8 describes.
"""
from psycopg import Cursor

from contradiction.detector import ExistingMemory


def resolve_contradictions(
    cur: Cursor,
    tenant_id: str,
    new_memory_id: str,
    new_confidence: float,
    candidates: list[ExistingMemory],
) -> list[str]:
    """Marks every candidate the new memory outranks as superseded, pointing
    it at `new_memory_id` (data_model.md's `superseded_by`) so the history
    stays auditable. Returns the ids actually superseded."""
    superseded_ids: list[str] = []
    for candidate in candidates:
        if new_confidence < candidate.confidence:
            continue
        cur.execute(
            """
            UPDATE memory
            SET status = 'superseded', superseded_by = %s, updated_at = now()
            WHERE id = %s
            """,
            (new_memory_id, candidate.id),
        )
        cur.execute(
            """
            INSERT INTO audit_log (tenant_id, actor, action, memory_id, detail)
            VALUES (%s, 'contradiction_resolver', 'replaced', %s, %s)
            """,
            (
                tenant_id,
                candidate.id,
                f"superseded by {new_memory_id} (confidence {new_confidence} >= {candidate.confidence})",
            ),
        )
        superseded_ids.append(candidate.id)
    return superseded_ids
