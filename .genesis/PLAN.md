# PLAN — conversational-memory-intelligence-system

The machine-parseable implementation plan. Mirrors the milestone table in `DONE.html` (DONE.html is the
human/visual view; this is the one loops read). Sliced so each milestone ships in one L1 BUILD pass.

> Slicing rule: a milestone must have (a) a single clear outcome, (b) an exact **demo command** that
> proves it, and (c) a freeze boundary of files it may touch. If you can't write the demo command,
> the milestone is too vague — split it.

---

## Brainstorm (G0.5 — fill before slicing milestones)

> Three fundamentally different approaches to the cognitive job. Pick one. Record the rationale.
> This is the cheapest design decision — you haven't written a line of code yet.

### Approach A — Vector-only similarity search
Store everything as embeddings, retrieve purely by cosine similarity.
- Strengths: simplest to build, one index type.
- Weaknesses: measured F4 (exact-fact miss) directly against this in the baseline — misses names, version numbers, exact terms. Rejected by the baseline experiment (D3) before this genesis run even started.

### Approach B — Hybrid search in one PostgreSQL database (vector + keyword + entity), AI-judge write gate, recency-weighted contradiction handling
One Postgres database does vector search, keyword (BM25-style) search, and entity matching at once; scores combined and reranked. Write gate is an LLM judge (graduating to a trained classifier later, per A1/backlog). Contradictions resolved by recency + confidence weighting, not a bi-temporal graph.
- Strengths: ships a correct first version without operating multiple databases; keyword matching alone already fixes F4 per the D3 baseline finding; avoids the cost/latency of graph processing on every query.
- Weaknesses: the "newer wins" rule is a cheap approximation — may not hold on benchmark questions about facts that change over time; would need the bi-temporal graph (D1 backlog) if it fails those questions.

### Approach C — Bi-temporal knowledge graph + separate vector/graph stores + trained classifier write gate from day one
Zep-style two-date-per-fact model (valid-time + record-time) in a dedicated graph database, separate vector store, and a pre-trained (not LLM-judge) write-gate classifier.
- Strengths: best known answer for stale-memory correctness (63.8% vs Mem0's 49.0% on the cited benchmark); no LLM-judge consistency problem from day one.
- Weaknesses: a whole new database to operate; graph processing adds latency to every question; no training data yet for a classifier without circular reasoning (open question in design_backlog.md). Overbuilt for a first version per ADR-002.

### Chosen: Approach B — hybrid Postgres search + AI-judge write gate, per ADR-002 and ADR-003. Postpone Approach C behind the named trigger already recorded in the design backlog (D1, D2): revisit the bi-temporal graph only if the recency/confidence rule fails the benchmark's fact-change questions; revisit the trained classifier once write-gate decision volume/cost justifies it and training labels exist without circular reasoning.

---

## Milestones

### M0 — Foundation, and keeping users apart
- **Outcome:** One PostgreSQL database holding memories + all three search indexes; row-level security refuses cross-user reads; skeleton send-message / get-memories endpoints.
- **Phase (swe-master):** Phase 1 (Architecture) + Phase 3 (Backend) + Phase 11 (Security, INV-1)
- **Files / freeze boundary:** `implementation/db/**`, `implementation/api/**`
- **Demo command:** `pytest implementation/tests/test_tenant_isolation.py -v`
- **Success criteria:** cross-user attack test shows zero leaks (down from 0.92 baseline) — hard gate. A query with no user filter is refused by the database itself, not caught in application code.
- **Loops:** L1, L4
- **Skills:** canon + tdd + data-systems-engineering + security-engineering
- **Token budget:** 50000

### M1 — The write gate, secrets, and pulling facts out
- **Outcome:** Single-pass fact extraction; secrets filter runs before any write; AI-judge write gate logs every decision (future classifier training data).
- **Phase:** Phase 5 (LLM/Reasoning) + Phase 6 (Memory) + Phase 11 (Security, INV-2)
- **Files:** `implementation/write_gate/**`, `implementation/extraction/**`
- **Demo command:** `pytest implementation/tests/test_write_gate.py -v`
- **Success criteria:** secrets findable drops to zero (down from 1.00); secrets test passes in both directions (real keys blocked, innocent phrases not blocked) — hard gate. Relevant-results rate improves above 0.20, aiming above 0.6.
- **Loops:** L1, L4
- **Skills:** canon + tdd + llmops-ai-agents + security-engineering
- **Token budget:** 50000

### M2 — Search and ranking
- **Outcome:** Hybrid search (vector + keyword + entity) combined into one score; ranking on similarity/recency/importance/frequency; relevance bar so the system can say "I don't know."
- **Phase:** Phase 6 (Memory) — RAG/hybrid retrieval gate
- **Files:** `implementation/retrieval/**`
- **Demo command:** `pytest implementation/tests/test_retrieval.py -v`
- **Success criteria:** stays silent on unanswerable questions instead of guessing; exact-fact questions answered correctly; lookups finish under 100ms at every store size.
- **Loops:** L1, L3 (research), L4
- **Skills:** canon + tdd + llmops-ai-agents + data-systems-engineering
- **Token budget:** 50000

### M3 — Handling contradictions
- **Outcome:** Write-time check against existing memories on the same subject; newer+more-confident wins; old memory kept with a pointer to what replaced it; user-facing "that's wrong" correction endpoint.
- **Phase:** Phase 6 (Memory) + Phase 3 (Backend, correction endpoint)
- **Files:** `implementation/contradiction/**`, `implementation/api/**`
- **Demo command:** `pytest implementation/tests/test_contradiction.py -v`
- **Success criteria:** outdated preference wins < 0.33 of the time (down from 0.33 baseline), aiming near-zero — hard gate. Replaced memory's history is still there and auditable.
- **Loops:** L1, L2, L4
- **Skills:** canon + tdd + data-systems-engineering
- **Token budget:** 50000

### M4 — Forgetting, archiving, and deletion
- **Outcome:** Nightly job recalculates importance×recency×usefulness per memory, archives faded ones, finishes pending deletions.
- **Phase:** Phase 12 (Reliability) + Phase 14 (Data Engineering)
- **Files:** `implementation/forgetting/**`, `implementation/jobs/**`
- **Demo command:** `pytest implementation/tests/test_forgetting.py -v`
- **Success criteria:** store stops growing unboundedly under constant writes; frequently-used memories are not archived by mistake. Deletion test: gone from reads instantly, gone from search within 60s — hard gate (INV-4).
- **Loops:** L1, L4
- **Skills:** canon + tdd + data-systems-engineering
- **Token budget:** 50000

### M5 — Monitoring and testing
- **Outcome:** The four health numbers (usage rate, correction rate, latency, cost) wired to a dashboard; Deliverable-3 benchmark re-run end to end; graceful no-memory degradation when the store is down.
- **Phase:** Phase 9 (Evaluation) + Phase 10 (Observability) + Phase 12 (Reliability, C13)
- **Files:** `implementation/observability/**`, `implementation/benchmark.py`
- **Demo command:** `python implementation/benchmark.py --compare-baseline experiments/baseline_results.csv`
- **Success criteria:** full Deliverable-3 test re-run and reported side by side against the naive baseline — hard gate, exact comparison required. Outage test: memory store failure never fails the turn, assistant answers without memory.
- **Loops:** L1, L4
- **Skills:** canon + tdd + llmops-ai-agents + production-readiness
- **Token budget:** 50000

### M6 (stretch) — The prototypes
- **Outcome:** Second-pass reranking model behind a feature switch (P1); early trained classifier to eventually replace the AI-judge write gate (P2).
- **Phase:** Phase 5 (LLM/Reasoning), prototyping track
- **Files:** `implementation/prototypes/**`
- **Demo command:** `pytest implementation/tests/test_prototypes.py -v -m stretch`
- **Success criteria:** P1/P2 experiments from design_backlog.md decide adopt/reject — accuracy gain must justify latency cost (P1, must stay <100ms), extraction must match naive extractor's recall for less cost (P2).
- **Loops:** L1, L3 (research), L4
- **Skills:** canon + tdd + llmops-ai-agents
- **Token budget:** 50000

---

## Progress (loops append here on milestone completion — newest last)

- **2026-07-14 — M0 DONE.** One PostgreSQL database (isolated docker-compose stack, port 5433, separate from the real commenthook stack), row-level security on all 4 tables (`memory`, `memory_entity`, `conversation_turn`, `audit_log`), skeleton `POST /messages` / `GET /memories` behind a verified-token auth stub. Demo: `pytest implementation/tests/test_tenant_isolation.py -v` → 5/5 passed, cross-tenant leak = 0 (down from 0.92 baseline), unfiltered query refused by the database itself. L4 VERIFY (claude-opus-4-8, fresh context) → APPROVE. Quiz-me gate answered by human, logged in `checkpoints/M0.md`. Hardening note surfaced during the quiz: the `cmis` table-owner role is a Postgres superuser (default behavior of the official image) and unconditionally bypasses RLS — nothing beyond one-time schema setup should ever connect as `cmis`.
- **2026-07-14 — M1 DONE.** Single-pass fact extraction and an AI-judge write gate (`implementation/write_gate/**`, `implementation/extraction/**`), secrets filter checked synchronously before any write, extraction/write-gate running in the background (FastAPI `BackgroundTasks`) after the response returns (ADR-005). `POST /messages`/`GET /memories` renamed to the real `POST /v1/memories:ingest`/`GET /v1/memories` contract from `api_contracts.md`. Judge/extractor are swappable interfaces — `AnthropicWriteGateJudge`/`AnthropicFactExtractor` in production, deterministic `FakeJudge`/`FakeExtractor` injected in tests. Demo: `pytest implementation/tests/test_write_gate.py -v` → 13 passed (18/18 suite at the time). L4 VERIFY: attempt 1 was UNCERTAIN/leaning REJECT — detector missed several threat_model.md-named in-scope secret shapes (SSN, JWT, bare hex/mixed tokens, Stripe/GitHub prefixes) → L2 DEBUG added those patterns + regression tests (24/24 after fix) → attempt 2 APPROVE. Quiz-me gate answered by human, logged in `checkpoints/M1.md`.
- **2026-07-17 — M2 DONE.** Hybrid search (`implementation/retrieval/**`): vector similarity + keyword (`ts_rank_cd`, normalized) + entity match combine into one `semantic` signal (C7), blended with recency/frequency/importance into final rank (C6); relevance floor (`RELEVANCE_FLOOR = 0.20`) gates per-candidate on `semantic` before selection so the system abstains honestly (INV-6) without a recent/important-but-irrelevant memory suppressing a real answer; token-budget cap enforced (INV-3). `write_gate/pipeline.py` now calls `retrieval.indexer.index_memory(...)` at write time so `embedding`/`memory_entity` are actually populated (declared out-of-boundary touch, flagged in G0 micro-plan up front). `api/main.py` gained `POST /v1/memories:retrieve` per `api_contracts.md`. Demo: `pytest implementation/tests/test_retrieval.py -v` → 11/11 passed (35/35 full suite), mypy clean, ruff clean. L4 VERIFY: attempt 1 REJECTed a genuine bug (abstention gated on top-by-final-score item instead of per-candidate `semantic`, causing false abstentions when a distractor outranked the real answer) → L2 DEBUG fixed it + added a regression test → attempt 2 APPROVE. Quiz-me gate answered by human, logged in `checkpoints/M2.md`.
- **2026-07-18 — M3 DONE.** Write-time contradiction handling (`implementation/contradiction/**`): `detector.py::find_same_subject()` self-joins `memory` on the new row's already-populated `embedding` column (no re-embedding) to find active same-type candidates above `SAME_SUBJECT_THRESHOLD = 0.75` cosine similarity, exempting append-only/session-scoped `event`/`working` types; `resolver.py::resolve_contradictions()` applies C8's rule — new memory supersedes a candidate only if at least as confident (`new_confidence >= candidate.confidence`), otherwise both stay active — setting `status='superseded'` + `superseded_by=<new id>` and logging `audit_log(action='replaced')` on the loser, never deleting it. `db/schema.sql`'s `memory.status` CHECK constraint extended with `'superseded'` (picked over data_model.md's "replaced" label to match the wire literal in `api_contracts.md`'s feedback response), live dev DB constraint altered directly since `conftest.py` only applies schema.sql once. `write_gate/pipeline.py` wired to call the detector+resolver pair right after indexing. `api/main.py` gained `POST /v1/memories:feedback` (`{memory_id, signal:"outdated"}` → `{superseded, new_status}`), with undocumented edge cases decided in the micro-plan: unknown/cross-tenant id → 404, already-non-active memory → 200 idempotent (no silent overwrite). Demo: `pytest implementation/tests/test_contradiction.py -v` → 10/10 passed (45/45 full suite), mypy clean (27 files), ruff clean. L4 VERIFY (claude-opus-4-8, fresh context, live adversarial scenarios against Postgres): attempt 1 APPROVE — double-supersede, equal-confidence tie (new wins, satisfies INV-5), lower-confidence both-kept, no chain-superseding a dead row, cross-tenant self-join returns 0 candidates (no INV-1 leak), feedback endpoint's full edge-case matrix (422/401/404/idempotent-200), all queries parameterized. Non-blocking caveats: `SAME_SUBJECT_THRESHOLD` tunable, `feedback` leaves `superseded_by` NULL by design (audit trail lives in `audit_log` instead), no `FOR UPDATE` on the feedback read (cosmetic double-audit-row risk under concurrent duplicate requests). Quiz-me gate answered by human, logged in `checkpoints/M3.md`.
