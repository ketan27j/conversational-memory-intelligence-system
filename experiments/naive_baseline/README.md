# Naive Baseline — Productive Failure Experiment (D3)

A deliberately simple conversational-memory baseline, built to make its own failures
measurable. Store everything, rank on one similarity signal (TF-IDF cosine), no recency,
no isolation, no admission gate, no decay, no abstention.

## Run

```bash
pip install -r requirements.txt
python benchmark.py
```

Outputs (written to the parent `experiments/` folder):
- `baseline_results.csv` — tidy metrics at four store sizes
- `error_examples.jsonl` — concrete failing retrievals at the largest store size

Deterministic: fixed seed (42), deterministic TF-IDF, fixed probe set. Re-running reproduces identical output.

## Files

- `memory.py` — `NaiveMemoryStore`. Every naive choice is commented with the capability (C#) it omits and the failure (F#) it should expose.
- `workload.py` — seeded workload generator. Filler haystack + labelled scenario memories + probes with ground truth, covering the six required scenarios (S1–S6).
- `benchmark.py` — runs the workload at four store sizes, measures every failure mode against ground truth, writes the CSV and JSONL.

## What it measures

Pollution (precision@5), stale-preference wins, cross-tenant leak rate, PII admission/exposure,
context-budget token usage, cold-start abstention failure, storage growth, and retrieval latency.

See `../baseline_protocol.md` for the pre-registered plan and `../productive_failure_report.pdf` for findings.

## Honest limitations

- TF-IDF keyword matching is strong on exact-string facts, so the dense-embedding failure F4
  (exact-fact miss) is not reproduced here by design — see the protocol.
- "Response quality" is measured as retrieval/context quality against ground truth (no LLM in the
  loop), which is more rigorous for these failure modes but does not test generation. Wiring an
  LLM judge against LongMemEval-S (adopted in D2) is the next step.
