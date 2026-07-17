"""Populates the two signals hybrid search needs on every stored memory:
the embedding (meaning) and the entity rows (linked names). Gap found in
M2's G0 pre-flight (checkpoints/M2.md): write_gate/pipeline.py stores a
memory's content but never indexes it — without this, `memory.embedding`
stays NULL and `memory_entity` stays empty for every real write, so hybrid
search would only ever work against hand-seeded test fixtures.
"""
from psycopg import Cursor

from retrieval.embedder import Embedder
from retrieval.entity_extractor import extract_entities


def _to_pgvector(vector: list[float]) -> str:
    return "[" + ",".join(repr(v) for v in vector) + "]"


def index_memory(cur: Cursor, memory_id: str, tenant_id: str, content: str, embedder: Embedder) -> None:
    """Must run on the same tenant-scoped connection/cursor the memory row
    was written on (RLS applies to the UPDATE/INSERT here same as anywhere else)."""
    vector = embedder.embed(content)
    cur.execute(
        "UPDATE memory SET embedding = %s::vector WHERE id = %s",
        (_to_pgvector(vector), memory_id),
    )

    entities = extract_entities(content)
    for entity in entities:
        cur.execute(
            """
            INSERT INTO memory_entity (memory_id, tenant_id, entity)
            VALUES (%s, %s, %s)
            ON CONFLICT (memory_id, entity) DO NOTHING
            """,
            (memory_id, tenant_id, entity),
        )
