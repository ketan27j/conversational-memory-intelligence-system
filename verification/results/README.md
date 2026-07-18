# Results index

All files here are raw or lightly-summarized output from independent re-runs performed for
Deliverable 6, on 2026-07-18, against a freshly recreated database volume — not copied from
`.genesis/checkpoints/`'s build-time claims.

| File | What it is |
|---|---|
| `pytest_output.txt` | Full `pytest tests/ -v` run — 71/71 passed |
| `static_analysis_output.txt` | `mypy --config-file mypy.ini .` and `ruff check .` — both clean |
| `benchmark_output.txt` | Raw output of `python3 -m benchmark --compare-baseline experiments/baseline_results.csv` |
| `benchmark_comparison.md` | Annotated read of the benchmark output against the handbook's non-negotiable gates, including the one metric (S6 abstention) that improved but did not reach zero |
| `rls_spot_check.txt` | Live `psql` session, run directly as the production `cmis_app` role (bypassing the Python/FastAPI layer entirely), proving row-level security holds at the database layer for a foreign tenant and for a session that never sets a tenant at all |

Reproduce any of these yourself:

```bash
cd implementation
docker compose down -v && docker compose up -d   # fresh volume
python3 -m pytest tests/ -v                        # applies schema.sql automatically (conftest.py)
python3 -m mypy --config-file mypy.ini .
python3 -m ruff check .
python3 -m benchmark --compare-baseline ../experiments/baseline_results.csv
```
