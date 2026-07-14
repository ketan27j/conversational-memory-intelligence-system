# Project

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
