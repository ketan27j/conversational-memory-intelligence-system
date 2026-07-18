# Decision records

This directory exists to satisfy the handbook's literal `design/decision_records/ADR-NNN-title.md`
path (Deliverable 7). The files here are symlinks to the canonical ADRs at `design/ADR-*.md`,
which were written and cross-referenced from that location throughout the project (`PLAN.md`,
every `.genesis/checkpoints/*.md` file, and multiple ADRs' own "supersedes/depends on" links all
point to `design/ADR-NNN-*.md`). Symlinking rather than duplicating avoids two copies of each
decision record silently drifting apart.

| ADR | Decision |
|---|---|
| ADR-001 | Write gate stays an AI judge for now; graduate to a trained classifier later (prototyped at M6) |
| ADR-002 | Hybrid search (vector + keyword + entity) in one Postgres database; defer a bi-temporal graph |
| ADR-003 | One Postgres database, not separate stores per index type |
| ADR-004 | Tenant separation lives inside the database (RLS), not in application code |
| ADR-005 | Secrets are checked before anything else, synchronously, before any write |
| ADR-006 | A second-pass reranker ships behind a switch, off by default (prototyped and rejected at M6 on latency) |
| ADR-007 | The forgetting/decay formula stays a simple, hand-tunable weight, not a learned model |
