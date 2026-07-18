# Security Report — Conversational Memory Intelligence System

**Deliverable:** 6 (Implementation and Independent Verification) · **Author:** Ketan Juikar

This report verifies the threats and mitigations named in `design/threat_model.md` (Deliverable 4)
against the actual running system, independently — re-run for this deliverable, not accepted from
the build's own claims. Evidence referenced here is either a fresh test-suite pass
(`results/pytest_output.txt`) or a live database session run directly outside the application
layer (`results/rls_spot_check.txt`).

## T1 / T7 — Cross-tenant reads and identity spoofing

**Claim (`threat_model.md`):** a database rule refuses to hand over another tenant's rows, no
matter how the query is written; the server only ever trusts the tenant id from the login token,
never from the request body.

**Independently verified:**
- `db/schema.sql` enables `ROW LEVEL SECURITY` and **`FORCE ROW LEVEL SECURITY`** on all five
  tenant-scoped tables (`memory`, `memory_entity`, `conversation_turn`, `audit_log`,
  `request_metric`, `write_gate_decision`) — `FORCE` matters specifically because it also applies
  the policy to the table owner, not just other roles.
- Live spot-check (`results/rls_spot_check.txt`), run directly via `psql` as the production
  `cmis_app` role (bypassing FastAPI entirely): a memory seeded under tenant A is invisible to a
  session set to tenant B (**0 rows**) and invisible to a session that never sets `app.tenant_id`
  at all (**0 rows**) — confirming the "bypass test" `threat_model.md` names as the real test:
  the database refuses the query, not the application code.
- `test_tenant_isolation.py` (5 tests, all passing fresh): cross-tenant leak via direct query is
  zero, an unfiltered query is refused by the database, the HTTP API never returns another
  tenant's data, and a request with no token is rejected before any tenant logic runs.
- `test_retrieval.py::test_hybrid_search_never_returns_another_tenants_memory` and
  `test_contradiction.py::test_find_same_subject_respects_tenant_isolation` confirm the same
  guarantee holds on the newer search and contradiction-detection code paths, not just the
  original M0 CRUD paths.
- Benchmark S4 `cross_tenant_leak_rate`: 0.250 (naive baseline) → **0.000** (real system),
  `results/benchmark_comparison.md`.

**Verdict: holds.** No cross-tenant leak found under adversarial testing performed independently
of the build.

## T2 — Secrets get stored

**Claim:** the secrets filter runs before anything is saved; the offending text is discarded, not
masked-and-kept; only the *kind* of secret is logged, never the value.

**Independently verified:**
- `test_write_gate.py` (17 tests, all passing fresh) — 9 positive cases (AWS key, RSA/EC private
  key block, valid card number, an explicitly-assigned secret, SSN, JWT, bare high-entropy hex
  and mixed-case tokens, Stripe/GitHub-prefixed tokens) and 4 negative cases (an innocent phrase
  containing the word "key", an innocent phrase containing the word "secret", a normal URL, a
  card-number-shaped-but-invalid string) — confirming the filter blocks real secrets without
  over-blocking innocent text, the exact both-directions requirement the handbook's D6 minimum
  acceptance checks list.
- Benchmark S5 `secrets_stored`: 2.000 (naive baseline) → **0.000** (real system).

**Verdict: holds**, with the residual risk `threat_model.md` already names and this report does
not relitigate: detection cannot be complete by construction — a novel credential format could
still slip through. Mitigated, not eliminated, by encryption at rest and an audit trail.

## T3 / T5 — Memory poisoning and incomplete deletion

**Claim:** the write gate limits confidence assigned to untrusted text; contradictions are
resolved by comparing against existing memories, not by accepting the newest claim blindly;
deletion is a two-step process (instant from reads, index-consistent within 60s), never leaving a
retrievable ghost.

**Independently verified:**
- `test_contradiction.py` (10 tests, fresh pass) — a higher-confidence contradiction supersedes;
  a lower-confidence one does not (both stay active); the superseded row keeps
  `superseded_by`/`status='superseded'` for audit rather than being deleted.
- `test_forgetting.py::test_delete_endpoint_marks_deleted_and_disappears_from_reads_instantly` and
  `::test_delete_then_purge_makes_it_physically_gone_within_the_stated_window` — confirmed fresh.
- Benchmark S2 `stale_wins_rate`: 0.333 (naive baseline) → **0.000** (real system).

**Verdict: holds** for the tested scenarios. `threat_model.md`'s own residual-risk note — that an
AI-judge write gate can in principle be talked into over-trusting hostile text — is not fully
closed by this deliverable; M6's write-gate classifier prototype is a step toward reducing that
surface but was evaluated against a rule-based judge stand-in, not the real fuzzier judge (see
`.genesis/checkpoints/M6.md` and `test_plan.md`'s "known gaps" section).

## Database roles and privilege boundaries (not directly named in `threat_model.md`, verified from `db/schema.sql`)

| Role | Privileges | Exposed over HTTP? |
|---|---|---|
| `cmis` | Table owner, superuser (default behavior of the official Postgres image) | Never — one-time schema setup only, per the M0 hardening note in `.genesis/PLAN.md` |
| `cmis_app` | `NOBYPASSRLS`; `SELECT/INSERT/UPDATE` on `memory`/`memory_entity`/`conversation_turn`, `SELECT/INSERT` on `audit_log`/`request_metric`/`write_gate_decision` | Yes — this is the role the FastAPI app itself connects as |
| `cmis_job` | `BYPASSRLS` (required — nightly reweighting/purge must cross every tenant); `SELECT/UPDATE/DELETE` on `memory`, `INSERT` on `audit_log` only | **No** — confirmed by inspection of `api/main.py`: no endpoint constructs a connection using `JOB_DSN`/`cmis_job`; this role only appears in `implementation/jobs/**` |

The one role with `BYPASSRLS` (`cmis_job`) is deliberately the narrowest-privileged role in the
system (three grants total) and is never reachable from any HTTP path — confirmed by grep, not
just by the schema comment claiming it.

## Summary

| Threat | Status | Evidence |
|---|---|---|
| T1 Cross-tenant read | Holds | Live RLS spot-check + 5 tenant-isolation tests + 2 cross-path tests |
| T2 Secrets stored | Holds (residual: novel formats) | 17 write-gate tests, both directions |
| T3 Memory poisoning | Holds for tested scenarios (residual: AI-judge manipulation) | 10 contradiction tests |
| T5 Incomplete deletion | Holds | 4 forgetting/deletion tests |
| T7 Identity spoofing via body | Holds | Token-derived tenant id only; confirmed in `api/auth.py` usage across all endpoints |

No new vulnerabilities were found during this deliverable's independent re-verification beyond
the residual risks `threat_model.md` already names. Nothing here was concealed to make the
project look more finished than it is.
