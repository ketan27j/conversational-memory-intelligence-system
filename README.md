# Conversational Memory Intelligence System

A system that decides what conversational information should be retained, represents and stores
it safely, retrieves and ranks relevant memories, injects them into model context, and manages
reflection, decay, and tenant isolation. Built as the primary project for the *Learning Through
Reconstruction* AI Engineering handbook, across seven Genesis loops (`M0`–`M6`, see
`.genesis/PLAN.md`).

## Architecture summary

One PostgreSQL database (pgvector extension) holds everything — memories, all three search
indexes (vector via HNSW, keyword via `tsvector`/`ts_rank_cd`, entity via a join table), audit
log, and per-request metrics. Row-level security enforces tenant isolation at the database layer
itself, not in application code (`design/ADR-004-separation-inside-the-database.md`). A FastAPI
service sits in front of it:

| Concern | Module | Notes |
|---|---|---|
| Tenant isolation | `db/` | RLS on every table, three roles (`cmis` owner/setup-only, `cmis_app` the API's own NOBYPASSRLS role, `cmis_job` a narrowly-scoped BYPASSRLS role for nightly jobs, never exposed over HTTP) |
| Extraction + write gate | `extraction/`, `write_gate/`, `secrets_filter/` | Secrets are filtered synchronously before any write; an AI-judge decides keep/drop and logs every decision (training data for a future classifier, `design/ADR-001-*.md`) |
| Retrieval and ranking | `retrieval/` | Hybrid search (vector + keyword + entity) blended into one score; a relevance floor causes honest abstention instead of guessing |
| Contradictions | `contradiction/` | Write-time same-subject detection; newer + at-least-as-confident supersedes, loser kept for audit, never deleted |
| Forgetting | `forgetting/`, `jobs/` | Nightly reweighting (importance × recency × usefulness) archives faded memories; deletion is instant from reads, physically purged within a documented window |
| Observability | `observability/` | The four health numbers (usage rate, correction rate, latency, cost); graceful `503` degradation when the store is unreachable, never fails the turn |
| Prototypes (stretch) | `prototypes/` | Second-pass reranker and a write-gate classifier, both behind feature switches, off by default |
| HTTP API | `api/main.py` | See endpoints below |

### API endpoints (`design/api_contracts.md`)

- `POST /v1/memories:ingest` — accept a conversation turn; extraction/write-gate run in the background after the response returns
- `GET /v1/memories` — list the caller's own memories
- `POST /v1/memories:retrieve` — hybrid search + ranking, with an optional `rerank` switch (off by default)
- `POST /v1/memories:feedback` — mark a memory outdated (triggers the contradiction-resolution supersede path)
- `DELETE /v1/memories/{id}` — delete a memory (idempotent)
- `GET /v1/observability/health` — the four health numbers, tenant-scoped

All endpoints derive the caller's tenant id from the bearer token (`Depends(verify_token)`) —
never from the request body.

## Setup

Requires Docker and Python 3.12+.

```bash
cd implementation
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

docker compose up -d          # starts Postgres + pgvector on localhost:5433
python3 -m pytest tests/ -v   # applies db/schema.sql automatically on first run (tests/conftest.py)
```

No API keys are required to run the test suite or the benchmark — every LLM-backed component
(extractor, judge, embedder, reranker) has a deterministic fake/offline implementation used in
tests (`C14` in the design docs). Set `ANTHROPIC_API_KEY` / `VOYAGE_API_KEY` to run the real
production judge/extractor/embedder instead.

To run the API itself:

```bash
uvicorn api.main:app --reload --port 8000
```

## Commands

| Task | Command |
|---|---|
| Run the full test suite | `pytest tests/ -v` (71 tests) |
| Run only the stretch-milestone prototype tests | `pytest tests/test_prototypes.py -v -m stretch` |
| Type-check | `mypy --config-file mypy.ini .` |
| Lint | `ruff check .` |
| Re-run the Deliverable-3 benchmark against the naive baseline | `python3 -m benchmark --compare-baseline ../experiments/baseline_results.csv` |
| Reset to a clean database volume (for a fair benchmark/verification run) | `docker compose down -v && docker compose up -d` |

Independent verification evidence (fresh re-runs of all of the above, plus a live database-level
security spot-check) lives in `verification/` — see `verification/test_plan.md` for what's tested
and why, and `verification/final_verification.pdf` for the consolidated verdict.

## Directory Structure

- **reconstruction/** - Reconstruction phase
- **research/** - Research and exploration
- **design/** - Design specifications and planning
- **experiments/** - Experimental work and prototypes
- **implementation/** - Implementation and development
- **verification/** - Testing and validation
- **transfer/** - Knowledge transfer and documentation
- **journal/** - Project journal and notes
- **.genesis/** - Genesis workflow configuration

## Notation

The project uses several short ID prefixes across documents. They are defined once, in the source document below, and referenced everywhere else — this table is just an index.

| Prefix | Meaning | Defined in | Example |
|--------|---------|------------|---------|
| **F#** | Failure — a way a simpler design breaks | `reconstruction/failure_analysis.md` | F4 = pure-vector exact-fact miss |
| **C#** | Capability — a system requirement derived from an F# failure | `reconstruction/first_principles.md` | C3 = write gate / admission policy, C11 = PII filtering + deletion path |
| **S#** | Scenario — a workload case in the baseline experiment | `experiments/baseline_protocol.md` | S1 = pollution, S2 = stale preference |
| **A#** | Backlog item, *Adopted* | `research/design_backlog.md` | A2 = multi-signal fused retrieval |
| **P#** | Backlog item, *Prototyping* (bounded experiment before adopt/reject) | `research/design_backlog.md` | P1 = cross-encoder reranking |
| **D#** (backlog) | Backlog item, *Deferred* (gated on a named trigger) | `research/design_backlog.md` | D1 = bi-temporal knowledge graph |
| **D#** (deliverable) | Course deliverable number, in each doc's `**Deliverable:**` header | per-document header | D1 = Problem Reconstruction, D2 = Research-to-Design Scan, D3 = Productive Failure Baseline |

**Note on the D# collision:** `D#` is overloaded — it means a *Deferred* backlog item in `design_backlog.md`'s tables, and a *Deliverable* number everywhere else (including the top-level `Deliverables/D1`, `Deliverables/D2` week folders, which are unrelated course submissions, not backlog entries). Disambiguate by context: inside the backlog table it's Deferred; in a `**Deliverable:**` header or a cross-reference like "D3 and D6," it's the deliverable.

Every F#, C#, and backlog item traces back through this chain: a failure (F#) forces a capability (C#), a capability is answered by a researched idea (A#/P#/D#), and adopted/prototyped ideas are exercised by baseline scenarios (S#).
