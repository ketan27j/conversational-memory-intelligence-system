"""Write-time contradiction detection (first_principles.md C8): before a new
fact/preference memory is considered final, find existing active memories
about the same subject so `resolver.py` can decide who wins.

Reuses the exact signal M2's hybrid search already trusts for "is this about
the same thing" — cosine similarity on the same `embedding` column — no new
similarity mechanism invented here. Runs *after* `retrieval/indexer.py` has
populated the new memory's own embedding, so this compares two already-stored
vectors instead of re-embedding the same content a second time.

'event' and 'working' memories are exempt: data_model.md says events are
"only ever added to" (append-only, never contradicted) and working memories
are session-scoped, never meant to be settled against long-term history.
"""
from dataclasses import dataclass

from psycopg import Cursor

# How similar two memories' embeddings must be to count as "the same subject"
# (not "the same answer" — this is deliberately looser than an exact-duplicate
# check but still high-precision, since a false positive here means silently
# superseding a *different*, still-true memory). Starting guess, tunable like
# M2's RELEVANCE_FLOOR and blend weights (ADR-002 precedent: "not a law").
SAME_SUBJECT_THRESHOLD = 0.75

# Types data_model.md says get overwritten/replaced over their lifetime.
# Event is append-only; working is session-scoped and never reaches
# long-term storage, so neither is ever a candidate for contradiction.
_CONTRADICTABLE_TYPES = ("fact", "preference")


@dataclass(frozen=True)
class ExistingMemory:
    id: str
    confidence: float
    similarity: float


def find_same_subject(cur: Cursor, memory_id: str, memory_type: str) -> list[ExistingMemory]:
    """Active, same-tenant (RLS-scoped by `cur`'s connection), same-type
    memories whose embedding is close enough to `memory_id`'s to be about the
    same subject. Never includes `memory_id` itself."""
    if memory_type not in _CONTRADICTABLE_TYPES:
        return []

    cur.execute(
        """
        SELECT other.id, other.confidence,
               1 - (other.embedding <=> new.embedding) AS similarity
        FROM memory new
        JOIN memory other
          ON other.status = 'active'
         AND other.type = new.type
         AND other.id != new.id
         AND other.embedding IS NOT NULL
        WHERE new.id = %s
          AND new.embedding IS NOT NULL
          AND 1 - (other.embedding <=> new.embedding) >= %s
        ORDER BY similarity DESC
        """,
        (memory_id, SAME_SUBJECT_THRESHOLD),
    )
    return [
        ExistingMemory(id=str(row[0]), confidence=float(row[1]), similarity=float(row[2]))
        for row in cur.fetchall()
    ]
