# Data Model — Conversational Memory Intelligence System

**Deliverable:** 4 (System Design) &middot; **Author:** Ketan Juikar

Every field below earns its place by making some later decision possible — ranking, forgetting, settling contradictions, security, or auditing.

That is the test I applied throughout: if nothing downstream ever reads a field, it does not belong in the design.

I have noted, next to each one, which capability (C) or measured failure (F) it traces back to.

---

## The main table: `memory`

This is the source of truth. One row for every memory we decided was worth keeping.

| Field | What it holds | Why it is there |
|-------|---------------|-----------------|
| `id` | A unique identifier | So we can refer to this memory |
| `tenant_id` | Which user this belongs to | **Every single read filters on this.** Fixes F5 (cross-tenant leak, which I measured at 0.92) — C10 (tenant isolation) |
| `type` | Event, fact, preference, or live conversation | Decides how long it lives and how it gets updated — C4 (memory types) |
| `content` | The fact itself, in plain words | Not a raw transcript — a short, clean fact — C2 (keep only what matters) |
| `embedding` | A numeric fingerprint of the meaning | Lets us search by meaning, not just exact words — C7 (hybrid search) |
| `content_tsv` | A searchable version of the words | Lets us search by exact keyword. Fixes F4 (exact-fact miss) — C7 |
| `importance` | A score from 1 to 10 | Used in ranking, and in deciding what fades. Set by the write gate — C5, C6 |
| `confidence` | How sure we are, from 0 to 1 | Used when two memories contradict each other — C5, C8 |
| `source_turn_id` | Which part of the conversation this came from | Lets the system answer "why do you think that?" — C5 (structured record) |
| `created_at` | When it was first stored | Used as the recency signal, and for auditing — C6 (multi-signal ranking) |
| `updated_at` | When it was last changed | Tracks when a memory got replaced — C8 (conflict resolution) |
| `last_accessed_at` | When it was last useful | Refreshes memories that keep proving their worth — C9 (forgetting) |
| `access_count` | How many times it has been used | A signal for both ranking and forgetting — C6, C9 |
| `weight` | How alive this memory still is | Calculated as importance × recency × usefulness — C9 |
| `status` | Active, archived, or deleted | Where it currently is in its life — C9, C11 |
| `superseded_by` | Points at whatever replaced this | So we can see what a memory turned into — C8 |

**Making search fast.** There are indexes on the user field (used by every query), on the meaning fingerprint, and on the keyword column.

**Keeping users apart — the important bit.** PostgreSQL has a feature that lets the *database itself* refuse to return rows belonging to anyone other than the current user. The rule lives in the database, not in the application code.

This matters enormously. It means a developer cannot accidentally leak data by forgetting to add a filter to one query, because the database will not hand the rows over in the first place. That is the direct structural fix for the 0.92 leak rate I measured in Deliverable 3, and it is the first of the seven rules (INV-1: no user ever sees another user's memory).

---

## Supporting table: `memory_entity`

This gives me the entity-matching search signal without having to run a separate graph database.

| Field | What it holds |
|-------|---------------|
| `memory_id` | Which memory this belongs to |
| `tenant_id` | Which user, so the separation rules still apply |
| `entity` | A cleaned-up name, such as `postgresql` or `acme_tools` |

When a memory is written, we pull out the names and things it mentions. When a question comes in, any names in the question boost the memories that mention them.

---

## Supporting table: `conversation_turn`

Where memories come from. This is what the `source_turn_id` field points at.

| Field | What it holds |
|-------|---------------|
| `id` | A unique identifier |
| `tenant_id` | Which user |
| `session_id` | Which conversation this was part of |
| `role` | Whether the user or the assistant said it |
| `text` | The raw words (kept only briefly) |
| `created_at` | When it was said |

Raw conversation gets deleted quickly. The short, clean facts we distilled from it are what actually last (C2).

---

## Supporting table: `audit_log`

This only ever gets added to, never edited. It records every write, every deletion, and every attempt to cross a boundary.

I need it for the security model, and for measuring how often users have to correct the system.

| Field | What it holds |
|-------|---------------|
| `id` | A running number |
| `tenant_id` | Which user |
| `actor` | A person, or a background job |
| `action` | Stored it, rejected it, retrieved it, replaced it, archived it, deleted it, or blocked it as a secret |
| `memory_id` | What was acted on |
| `detail` | Scores, reasons, and *what kind* of secret was blocked — never the secret itself |
| `created_at` | When it happened |

---

## The four types of memory, and their rules

| Type | Example | How it gets updated | How fast it fades |
|------|---------|---------------------|-------------------|
| Event | "Launched CommentHook in Q2" | Only ever added to | Slowly |
| Fact | "Uses PostgreSQL" | Overwritten, and duplicates removed | Slowly |
| Preference | "Prefers short answers" | **Replaced** when it changes. This is the structural fix for F3 (stale memory) | Very slowly, and it ranks high when retrieved |
| Live conversation | Facts from the current chat | Not saved at all, unless it earns promotion | Ends with the session |

The promotion path runs: **live conversation → session → long-term memory.** The write gate is what decides whether something moves up.

---

## The life of a memory

```
            gets past the gate                 fades below the floor
 candidate ────────────────────▶  active  ────────────────────────▶  archived
    │  ▲                            │  ▲                                │
    │  │ refreshed when useful      │  │ retrieved and helpful          │ brought back on demand
    ▼  │                            ▼  │                                ▼
 dropped                        replaced                         (cold storage)
                                    │
                        user asks to delete ──────▶  deleted  (gone from the database
                                                                and from search, within 60 seconds)
```

**Active becomes replaced.** A newer, more confident preference takes over from an older one. We keep the old row, with a pointer to whatever replaced it, so the change can be audited later. This is the fifth rule (INV-5: the current preference always beats the outdated one), and it is what fixes F3 (stale memory).

**Active becomes archived.** The memory's weight drops below the floor. It is **archived, not deleted** — so it can come back if needed, and its history survives (C9).

**Anything becomes deleted.** When a user asks, the memory goes from the database *and* the search index within 60 seconds. That is the fourth rule (INV-4).

---

## How deletion actually works

Deletion happens in two steps, and the order matters.

1. **Straight away.** The row is marked as deleted, and from that instant, no read will ever return it.
2. **Within 60 seconds.** A background job removes it from the search indexes as well.

The point of doing it in that order: even if the background job is running late, or crashes halfway, the memory is *already* invisible to every read. Nobody can retrieve something a user asked to delete.

That 60-second window is a promise we are making, and one we can tune. It is not an accident of how the code happens to work.
