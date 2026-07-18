# Benchmark Comparison — Real System vs. Naive Baseline (Deliverable 3)

Fresh re-run 2026-07-18, against a freshly recreated Docker volume (`docker compose down -v && up -d`),
schema re-applied immediately before the run. Raw output: `benchmark_output.txt`. Same seeded
workload (`experiments/naive_baseline/workload.py`, seed=42) driven through the real write path
(`write_gate.pipeline.process_turn`), not a raw `INSERT` — a raw-insert version was tried during
M5 and found to silently skip contradiction resolution, which would have made the S2 metric
measure nothing.

| Scenario | Metric | Naive baseline (D3) | Real system | Verdict |
|---|---|---:|---:|---|
| ALL | retrieval p50 latency (ms) | 0.41 | 15.16 | Higher, as expected for a real DB round-trip vs. an in-memory list; still far under the 100ms budget (INV: M2/M5 success criteria) |
| ALL | retrieval p95 latency (ms) | 0.69 | 18.73 | Same — comfortably under 100ms |
| S1 | precision@5 | 0.200 | 0.200 | Matches exactly |
| S1 | recall@5 | 1.000 | 1.000 | Matches exactly |
| S1 | hit@5 | 1.000 | 1.000 | Matches exactly |
| S1 | MRR | 0.938 | 0.792 | Lower but still strong — real hybrid ranking, not the baseline's single-signal similarity ranking |
| S2 | stale preference wins (rate) | 0.333 | **0.000** | **Fixed.** M3's write-time contradiction resolution eliminates stale-preference wins entirely (hard gate, PLAN.md M3) |
| S4 | cross-tenant leak (rate) | 0.250 | **0.000** | **Fixed.** M0's row-level security eliminates cross-tenant leakage entirely (hard gate, PLAN.md M0) |
| S5 | secrets stored (count) | 2.000 | **0.000** | **Fixed.** M1's write-time secrets filter blocks every secret in the workload (hard gate, PLAN.md M1) |
| S6 | abstention failure (rate) | 1.000 | 0.333 | **Improved, not eliminated.** M2's relevance floor causes honest abstention on most unanswerable questions but not all — see "Residual gap" below |

Store size at comparison: 63 memories (fixed seed, same as the checkpoint's own M5 run).

## Reading this table against the handbook's non-negotiable gates

The handbook requires the final design be compared against the naive baseline (§11.2) — this
table is that comparison, independently re-run for this deliverable rather than copied from the
build's own M5 checkpoint. Every metric this project declared a **hard gate** (cross-tenant leak,
secrets stored, stale-preference wins) reaches exactly **0.000**, not just "improved."

## Residual gap: S6 abstention failure rate (0.333, not 0.000)

This is reported here rather than hidden. `PLAN.md`'s M2 success criteria describes this as
"stays silent on unanswerable questions instead of guessing" without setting a numeric target —
unlike M0/M1/M3, which are explicit hard gates at zero. The relevance floor
(`RELEVANCE_FLOOR = 0.20` in `retrieval/search.py`) is documented in the M2 checkpoint as "a
starting guess, tunable," the same posture as the ranking blend weights. A lower floor would
catch more genuinely-relevant edge cases but risk surfacing false positives; this was not
re-tuned for Deliverable 6 since it is out of this deliverable's freeze boundary and the
trade-off is already documented at the point it was made.
