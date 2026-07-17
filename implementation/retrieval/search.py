"""Hybrid search + ranking (design/api_contracts.md `POST /v1/memories:retrieve`).

C7 (first_principles.md): three weak signals — vector similarity, keyword
match, entity match — combine into one semantic signal. C6: that semantic
signal is then blended with recency, frequency, and importance into the
final rank. ADR-002 already flags the blend weights as "a starting guess to
be tuned against a test set, not a law" — kept as named module constants so
that tuning pass has one place to land.

Runs on a tenant-scoped connection/cursor (db/connection.py's
`tenant_connection`); RLS does the tenant filtering here same as everywhere
else in this codebase, so no query below filters on tenant_id explicitly.
"""
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone

from psycopg import Cursor

from retrieval.embedder import Embedder
from retrieval.entity_extractor import extract_entities

# C7 weights: how the three raw hybrid-search signals combine into "semantic".
_W_VECTOR = 0.5
_W_KEYWORD = 0.3
_W_ENTITY = 0.2

# C6 weights: how "semantic" combines with recency/frequency/importance.
_W_SEMANTIC = 0.4
_W_RECENCY = 0.2
_W_FREQUENCY = 0.2
_W_IMPORTANCE = 0.2

_RECENCY_HALF_LIFE_DAYS = 30.0

# The relevance bar (INV-6): a candidate whose *semantic* match to the query
# is below this is treated as "not actually about this" regardless of how
# recent/important/frequent it is — recency/importance must never manufacture
# relevance out of an unrelated memory. Set to match sprint_plan.md's own
# 0.20 baseline-relevance reference point, tunable like the weights above.
RELEVANCE_FLOOR = 0.20


@dataclass
class _Candidate:
    id: str
    type: str
    content: str
    importance: int
    confidence: float
    created_at: datetime
    access_count: int
    similarity: float = 0.0
    keyword_rank: float = 0.0
    entity_hit: bool = False


@dataclass(frozen=True)
class ScoredMemory:
    id: str
    type: str
    content: str
    importance: int
    confidence: float
    created_at: datetime
    score: float
    semantic: float
    recency: float
    frequency: float


@dataclass(frozen=True)
class RetrieveResult:
    memories: list[ScoredMemory]
    abstained: bool
    tokens_used: int
    signals: dict[str, float] = field(default_factory=dict)


def _to_pgvector(vector: list[float]) -> str:
    return "[" + ",".join(repr(v) for v in vector) + "]"


def _estimate_tokens(content: str) -> int:
    """No tokenizer dependency added for this — a whitespace-word count is a
    deterministic, good-enough proxy for the token budget cap (INV-3)."""
    return max(1, len(content.split()))


def _recency_score(created_at: datetime, now: datetime) -> float:
    age_days = max(0.0, (now - created_at).total_seconds() / 86400.0)
    return math.pow(0.5, age_days / _RECENCY_HALF_LIFE_DAYS)


def _frequency_score(access_count: int) -> float:
    """Diminishing returns, bounded in [0, 1) with no arbitrary hard cap:
    half-max at 5 accesses."""
    return access_count / (access_count + 5.0)


def hybrid_search(
    cur: Cursor,
    query_text: str,
    embedder: Embedder,
    k_max: int = 8,
    token_budget: int = 512,
    pool_size: int = 50,
) -> RetrieveResult:
    query_vector = _to_pgvector(embedder.embed(query_text))
    query_entities = extract_entities(query_text)
    now = datetime.now(timezone.utc)

    candidates: dict[str, _Candidate] = {}

    def _get_or_create(row: tuple) -> _Candidate:
        mem_id = str(row[0])
        cand = candidates.get(mem_id)
        if cand is None:
            cand = _Candidate(
                id=mem_id,
                type=row[1],
                content=row[2],
                importance=row[3],
                confidence=row[4],
                created_at=row[5],
                access_count=row[6],
            )
            candidates[mem_id] = cand
        return cand

    # ── signal 1: vector similarity (meaning) ───────────────────────────────
    cur.execute(
        """
        SELECT id, type, content, importance, confidence, created_at, access_count,
               1 - (embedding <=> %s::vector) AS similarity
        FROM memory
        WHERE status = 'active' AND embedding IS NOT NULL
        ORDER BY embedding <=> %s::vector
        LIMIT %s
        """,
        (query_vector, query_vector, pool_size),
    )
    for row in cur.fetchall():
        cand = _get_or_create(row)
        cand.similarity = max(0.0, min(1.0, float(row[7])))

    # ── signal 2: keyword match (exact words — F4 exact-fact fix) ──────────
    cur.execute(
        """
        SELECT id, type, content, importance, confidence, created_at, access_count,
               ts_rank_cd(content_tsv, plainto_tsquery('english', %s)) AS keyword_rank
        FROM memory
        WHERE status = 'active' AND content_tsv @@ plainto_tsquery('english', %s)
        ORDER BY keyword_rank DESC
        LIMIT %s
        """,
        (query_text, query_text, pool_size),
    )
    keyword_rows = cur.fetchall()
    max_keyword_rank = max((float(row[7]) for row in keyword_rows), default=0.0)
    for row in keyword_rows:
        cand = _get_or_create(row)
        cand.keyword_rank = (float(row[7]) / max_keyword_rank) if max_keyword_rank > 0 else 0.0

    # ── signal 3: entity match (linked names) ──────────────────────────────
    if query_entities:
        cur.execute(
            """
            SELECT DISTINCT m.id, m.type, m.content, m.importance, m.confidence,
                   m.created_at, m.access_count
            FROM memory m
            JOIN memory_entity me ON me.memory_id = m.id
            WHERE m.status = 'active' AND me.entity = ANY(%s)
            LIMIT %s
            """,
            (query_entities, pool_size),
        )
        for row in cur.fetchall():
            cand = _get_or_create(row)
            cand.entity_hit = True

    # ── combine (C7) then rank (C6) ─────────────────────────────────────────
    scored: list[ScoredMemory] = []
    for cand in candidates.values():
        semantic = (
            _W_VECTOR * cand.similarity
            + _W_KEYWORD * cand.keyword_rank
            + _W_ENTITY * (1.0 if cand.entity_hit else 0.0)
        )
        recency = _recency_score(cand.created_at, now)
        frequency = _frequency_score(cand.access_count)
        importance = cand.importance / 10.0
        score = (
            _W_SEMANTIC * semantic
            + _W_RECENCY * recency
            + _W_FREQUENCY * frequency
            + _W_IMPORTANCE * importance
        )
        scored.append(
            ScoredMemory(
                id=cand.id,
                type=cand.type,
                content=cand.content,
                importance=cand.importance,
                confidence=cand.confidence,
                created_at=cand.created_at,
                score=score,
                semantic=semantic,
                recency=recency,
                frequency=frequency,
            )
        )

    scored.sort(key=lambda m: m.score, reverse=True)

    # INV-6: filter to candidates that are actually about the query *before*
    # picking a "top" result. Gating only on the top-by-final-score item is a
    # real bug, not just a stricter version of the same check: a highly
    # recent/important/frequent-but-unrelated memory can out-rank a genuinely
    # relevant one on final score, and would then fail the bar for the whole
    # query — a false abstention on an answerable question. Filtering
    # per-candidate keeps that distractor from suppressing a real answer
    # ranked below it, while still refusing to serve anything below the bar.
    relevant = [m for m in scored if m.semantic >= RELEVANCE_FLOOR]
    if not relevant:
        return RetrieveResult(memories=[], abstained=True, tokens_used=0, signals={})

    # INV-3: never exceed the token budget — greedily fill by rank, stop
    # before the budget would be exceeded (never after).
    selected: list[ScoredMemory] = []
    tokens_used = 0
    for mem in relevant:
        if len(selected) >= k_max:
            break
        cost = _estimate_tokens(mem.content)
        if tokens_used + cost > token_budget:
            continue
        selected.append(mem)
        tokens_used += cost

    if not selected:
        # Relevant candidates existed but none fit the budget. Returning
        # abstained=False with an empty list would be a contract wart (a
        # caller doing `if not abstained: memories[0]` would IndexError) —
        # from the caller's point of view "nothing deliverable" and "nothing
        # relevant" should look the same.
        return RetrieveResult(memories=[], abstained=True, tokens_used=0, signals={})

    top = selected[0]
    signals = {
        "semantic": round(top.semantic, 4),
        "recency": round(top.recency, 4),
        "frequency": round(top.frequency, 4),
        "importance": round(top.importance / 10.0, 4),
    }
    return RetrieveResult(memories=selected, abstained=False, tokens_used=tokens_used, signals=signals)
