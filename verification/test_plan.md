# Test Plan — Conversational Memory Intelligence System

**Deliverable:** 6 (Implementation and Independent Verification) · **Author:** Ketan Juikar

This plan defines what "verified" means for this system and where the evidence lives. It is
written from the handbook's Deliverable 6 acceptance checks and the invariants set in
`design/threat_model.md` and `.genesis/DONE.html`, not derived after the fact from whatever
tests happened to exist — each row below traces to a named requirement.

The system was built across seven Genesis loops (M0–M6, see `.genesis/PLAN.md`), each closed
by an independent L4 VERIFY pass (a separate model instance, fresh context, told to re-derive
evidence rather than trust the build's own claims). This document consolidates that verification
into the standalone artifact the handbook requires; `results/` holds the fresh, independently
re-run evidence backing it (re-run 2026-07-18 against a clean database volume specifically for
this deliverable, not copied from the build logs).

## Test levels

| Level | What it covers | Where |
|---|---|---|
| Unit / integration | Each component against a real Postgres instance (no mocked DB — `tests/conftest.py` spins up the real `docker-compose` stack and applies `db/schema.sql` fresh) | `implementation/tests/*.py`, 71 tests |
| End-to-end | Full HTTP request path through FastAPI's `TestClient` — ingest → extract → write-gate → index → retrieve → feedback → delete | `test_tenant_isolation.py`, `test_write_gate.py`, `test_retrieval.py`, `test_contradiction.py`, `test_forgetting.py`, `test_observability.py` |
| Evaluation (benchmark) | Same seeded workload (`experiments/naive_baseline/workload.py`, seed=42) run through the real write path, scored on the same metric set as the Deliverable 3 naive baseline | `implementation/benchmark.py`, `results/benchmark_comparison.md` |
| Adversarial / security | Cross-tenant leak attempts, RLS-bypass attempts, secrets-filter attempts (both directions), unroutable-store outage | `test_tenant_isolation.py`, `test_write_gate.py`, `test_observability.py`, plus a live `psql` spot-check independent of the test suite (see `security_report.md`) |
| Performance | p50/p95 retrieval latency at a realistic store size; 503 outage bounded by `connect_timeout` | `test_retrieval.py::test_latency_smoke_check_over_a_modest_store`, `test_observability.py::test_retrieve_returns_503_fast_when_store_unroutable`, `benchmark.py` |

## Test files and what each proves

| File | Tests | Proves |
|---|---|---|
| `test_tenant_isolation.py` | 5 | INV-1 — cross-tenant leak is zero; an unfiltered query is refused by the database itself, not application code (T1, T7 in `threat_model.md`) |
| `test_write_gate.py` | 17 | INV-2 — secrets never stored, tested both directions (real keys/tokens/SSNs blocked; innocent phrases not blocked); kept/dropped decisions are logged with recoverable candidate text |
| `test_retrieval.py` | 11 | Hybrid search combines vector + keyword + entity signals correctly; relevance floor causes honest abstention (INV-6); token budget is never exceeded; cross-tenant rows never surface in search results |
| `test_contradiction.py` | 10 | Write-time contradiction detection (C8) — higher-confidence memory supersedes, lower-confidence does not; superseded history stays auditable, never deleted; contradiction detection itself respects tenant isolation |
| `test_forgetting.py` | 13 | Nightly reweighting archives faded memories without archiving frequently-used ones; deletion is instant from reads and physically gone (cascade) within the documented window (INV-4); cross-tenant reweighting stays correctly scoped |
| `test_observability.py` | 6 | The four health numbers compute correctly from real audit/metric data; a memory-store outage returns `503` fast (bounded by `connect_timeout`) instead of hanging or failing the whole turn (C13/INV-7) |
| `test_prototypes.py` | 7 | Stretch milestone (M6) — reranker and write-gate classifier prototypes behave as specified and stay off by default |

**Total: 71 tests.** Fresh independent run: see `results/pytest_output.txt` — 71/71 passed against a
freshly recreated Docker volume (not the accumulated dev database).

## Mapping to the handbook's minimum acceptance checks (§8.3)

| Acceptance check | Satisfied by |
|---|---|
| Relevant memories outrank plausible distractors on the fixed evaluation set | `test_retrieval.py::test_relevant_answer_survives_an_unrelated_recent_important_distractor`, `::test_high_importance_and_recent_wins_the_tie`; `evaluation_dataset.jsonl` cases E1–E3 |
| Stale or superseded preferences do not override current preferences | `test_contradiction.py::test_higher_confidence_new_memory_supersedes_the_old_one` / `::test_lower_confidence_new_memory_does_not_supersede_the_old_one`; benchmark S2 `stale_wins_rate` (0.333 baseline → 0.000 real system) |
| No cross-tenant memory is returned under adversarial queries | `test_tenant_isolation.py` (5 tests), `test_retrieval.py::test_hybrid_search_never_returns_another_tenants_memory`, `test_contradiction.py::test_find_same_subject_respects_tenant_isolation`; independent live `psql` RLS spot-check in `security_report.md` |
| Deletion removes the memory from both source storage and retrieval paths within the documented consistency window | `test_forgetting.py::test_delete_endpoint_marks_deleted_and_disappears_from_reads_instantly`, `::test_delete_then_purge_makes_it_physically_gone_within_the_stated_window` |
| Context selection respects the configured token budget | `test_retrieval.py::test_never_exceeds_token_budget` |
| Sensitive-data policy is tested with positive and negative cases | `test_write_gate.py` — 9 positive (blocked) cases (AWS key, private key, card number, SSN, JWT, hex/mixed tokens, Stripe/GitHub prefixes) + 4 negative (not-blocked) cases in the same file |
| Benchmark results are compared with the naive baseline | `benchmark.py --compare-baseline experiments/baseline_results.csv`; `results/benchmark_comparison.md` |

## What independent verification means here, concretely

Per the handbook: *"Verification must be performed from the specification and acceptance
criteria, not by accepting the implementation agent's own assessment."* Two layers of that were
applied on this project:

1. **Per-milestone L4 VERIFY.** Every milestone (`.genesis/checkpoints/M0.md` through `M6.md`)
   was closed by a separate model instance given only the goal, success criteria, and invariants
   — not the build's own reasoning — and instructed to independently re-derive evidence (re-run
   commands itself, hand-derive expected values before driving the live system, seed its own
   adversarial data disjoint from the build's fixtures). All seven attempts returned **APPROVE**;
   two required one fix-and-reverify cycle first (M1, M2 — see `security_report.md` and
   `.genesis/PLAN.md`'s progress log for what was found and fixed).
2. **This deliverable's fresh re-run.** For Deliverable 6 specifically, the full suite, `mypy`,
   `ruff`, and `benchmark.py` were re-run again from a completely fresh Docker volume (not the
   accumulated development database), plus one additional live `psql` RLS check independent of
   the pytest suite. Raw output is in `results/`, not summarized-and-discarded.

## Known gaps and residual risk (reported, not concealed)

- The relevance-floor abstention rate (S6, `abstention_failure_rate`) improved from 1.000 to
  0.333 against the naive baseline but is not yet 0.000 — the handbook's own hard gates require
  the exact-fact and cross-tenant metrics to hit zero, and they do; abstention is a "measurably
  better, not perfect" metric per `PLAN.md`'s M2 success criteria, and the residual failure mode
  is documented in `results/benchmark_comparison.md`.
- Secret detection cannot be complete by construction — `threat_model.md` states this directly:
  a novel credential format could slip through. Mitigated by encryption-at-rest and an audit
  trail, not claimed to be solved.
- The write-gate classifier prototype (M6/P2) was measured against a rule-based judge stand-in,
  not the real fuzzier AI judge — its 1.000 held-out agreement is evidence the training mechanism
  works, not evidence the real judge is this cleanly learnable. Flagged in
  `implementation/prototypes/classifier_experiment.py`'s own docstring and in
  `.genesis/checkpoints/M6.md`.
- The reranker prototype (M6/P1) was rejected on latency (p95 ~178–185ms vs a ~100ms budget) and
  ships off by default — this is a documented reject, not a passed-then-hidden failure.
