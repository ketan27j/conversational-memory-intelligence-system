# Design Backlog — Conversational Memory Intelligence System

**Deliverable:** 2 (Research-to-Design Scan) — carried forward every week
**Owner:** Ketan Juikar
**Last updated:** Week 1, June 2026

This backlog is the memory of my research process.

Each item has a status, the failure it answers, and — for anything I have postponed — the exact thing that would make me pick it up again.

Nothing sits here vaguely "to consider." If I cannot say what would make me act on it, it does not belong on the list.

---

## Adopted — build these into the system design

| ID | The item | What it answers | Note |
|----|----------|-----------------|------|
| A1 | Use the LongMemEval benchmark as my main test set, and LoCoMo as a second opinion | C14 (repeatable testing) | These are shared test sets of long conversations with questions attached. Their question categories line up with F3 (stale memory) and with my cold-start case. I will fix which AI model does the judging, and which prompt it uses, and report both. |
| A2 | Search several ways at once — by meaning, by exact keyword, and by matching entities | F4 (exact-fact miss), C7 (hybrid search) | Adopt the pattern now; tune the weights against A1 once the test set is wired up. PostgreSQL can do all three searches in one database, so I avoid running a separate graph database for the first version. |

## Prototyping — a bounded experiment before I decide

| ID | The item | What it answers | The experiment, and what counts as success |
|----|----------|-----------------|--------------------------------------------|
| P1 | After the first search, pass the results through a second, more careful model that re-scores them | F4 (exact-fact miss) | Measure two things — how accurate the top results are, and how long the lookup takes — both with and without this step, on the multi-step questions. Adopt only if the accuracy gain is worth the delay, and only if lookups stay under about 100 milliseconds. |
| P2 | Pull clean facts out of a conversation in a single pass | F2 (memory pollution) | Measure how many facts it catches, and what it costs, against a naive extractor. Adopt if it catches just as much for less money. |

## Postponed — with a named trigger that would bring it back

| ID | The item | What it answers | What would make me pick it up |
|----|----------|-----------------|-------------------------------|
| D1 | Store two dates on every fact: when it was true, and when it was recorded (the approach Zep uses) | F3 (stale memory) | Pick this up if my simpler rule — weight recency, and let the newer, more confident memory win — scores badly on the benchmark questions about facts that change. This is the planned response, not a vague maybe. |
| D2 | Grow entity matching into a full graph search | F4 (exact-fact miss) | Pick this up if using entities as just one signal (item A2) turns out not to be enough for multi-step questions. |

## Rejected — with a reason, so I do not argue about it again

| ID | The item | Why not |
|----|----------|---------|
| R1 | Let the system *learn* what to forget, instead of following a fixed rule (Memory-R1, DeltaMem) | A first version does not need a machine-learned forgetting policy when a simple formula will do the job. I will revisit this only if tuning that formula by hand becomes a genuine bottleneck at scale. |

---

## Open questions still feeding this backlog

- When should the write gate stop being an AI judge and become a small trained classifier? And how do I get training labels for it without circular reasoning — that is, without training it on its own answers?
- Should users be separated by row-level security inside one shared database, or by giving each user their own storage? The right answer for a small product like CommentHook and for a regulated bank may not be the same.
- How fast must a deleted memory disappear from search?

These stay open until Deliverable 4, where each one becomes a proper decision record.

---

## What I will look at next week

Forgetting and the life of a memory — the part I looked at least this week. And keeping users apart, plus blocking sensitive data (my F5 and F6).

Those last two are non-negotiable gates in the handbook, and I have not yet scanned the field to see how people currently handle them.
