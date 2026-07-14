# Sprint Plan — Conversational Memory Intelligence System

**Deliverable:** 4 (System Design) &middot; **Author:** Ketan Juikar

The milestones are ordered so that each one closes a specific failure I actually **measured** in Deliverable 3.

And every milestone has to pass a test that is a **real number**, on the same test data the naive system already failed. That is the comparison the handbook treats as non-negotiable, and it is the thing that stops "it feels better now" from counting as progress.

---

## The numbers I have to beat

These are what the naive system scored, at 1,935 memories:

- **How much of what it returns is relevant:** only **0.20** — so 80% of the injected context was junk
- **How often the outdated preference wins:** **0.33** — one question in three
- **How often it leaks another user's memory:** **0.92** — eleven questions out of twelve
- **Secrets stored and findable:** **1.00** — every single one
- **How often it guesses instead of saying "I don't know":** **1.00** — always

---

## M0 — The foundation, and keeping users apart

**What I build.** One PostgreSQL database, holding the memories and all three ways of searching them. A database rule that stops any user from ever seeing another user's data. The skeleton of the send-a-message and get-memories calls.

**What it closes.** F5 (cross-tenant leak).

**What it has to pass:**
- The cross-user attack test: **zero leaks**, down from 0.92. **This is a hard gate.**
- A query with no user filter is refused by the *database*, not caught by application code.

## M1 — The write gate, secrets, and pulling facts out

**What I build.** Single-pass fact extraction. An immediate secrets filter. The write gate — running as an AI judge, and logging every decision it makes so those decisions become training data later.

**What it closes.** F2 (memory pollution), F6 (sensitive data).

**What it has to pass:**
- Secrets findable: **zero**, down from every single one. The secrets tests pass in both directions — real keys blocked, innocent phrases not blocked. **This is a hard gate.**
- Relevant results: **better than 0.20**, aiming for **above 0.6** once the gate has trimmed the junk out.

## M2 — Search and ranking

**What I build.** Search three ways at once — by meaning, by exact keyword, and by matching names — then combine the scores. Rank on similarity, recency, importance, and how often a memory gets used. And add a relevance bar, so the system can honestly say "I don't know."

**What it closes.** F4 (exact-fact miss), and the cold-start failure.

**What it has to pass:**
- It correctly stays silent on unanswerable questions, instead of guessing every time.
- Exact-fact questions get answered. And lookups still finish in under 100 milliseconds, even in the slowest cases, at every store size.

## M3 — Handling contradictions

**What I build.** A check, when writing, for whether this contradicts something we already know. Newer and more confident wins. The old memory is kept, with a pointer to what replaced it. Plus the call that lets users say "that's wrong."

**What it closes.** F3 (stale memory).

**What it has to pass:**
- The outdated preference wins **less than 0.33** of the time, aiming for roughly **never**. **This is a hard gate.**
- The replaced memory is still there, with its history intact, so the change can be audited.

## M4 — Forgetting, archiving, and deletion

**What I build.** A nightly job that recalculates how alive each memory still is (importance × recency × usefulness), archives the ones that have faded, and finishes off any deletions.

**What it closes.** F7 (memory explosion), and the deletion gate.

**What it has to pass:**
- The store stops growing forever, even under constant writing. And memories that keep getting used do **not** get archived by mistake.
- The deletion test: a deleted memory is gone from reads instantly, and gone from search within 60 seconds. **This is a hard gate.**

## M5 — Monitoring and testing

**What I build.** The four numbers that tell me whether memory is helping: how often it gets used, how often users correct it, how fast it is, and what it costs. The benchmark test set adopted in Deliverable 2. And graceful behaviour when the store goes down.

**What it closes.** C12 (observability), C13 (graceful degradation), C14 (repeatable testing).

**What it has to pass:**
- The full Deliverable 3 test is re-run, and the results reported side by side against the naive baseline. **This is a hard gate — the handbook demands this exact comparison.**
- The outage test: when the memory store fails, the assistant still answers the user, just without memory. It never fails the turn.

## M6 (stretch) — The prototypes

**What I build.** The second re-scoring model, behind a switch. And the beginnings of the trained classifier that will eventually replace the AI judge in the write gate.

**What it has to pass:** The specific experiments already written down in the Deliverable 2 backlog decide whether either of these gets switched on by default.

---

## The gates, in one table

| The gate | What I measure | Where it starts → where it must get to |
|----------|----------------|----------------------------------------|
| Keeping users apart | How often another user's memory leaks | 0.92 → **zero** |
| Secrets | Secrets findable in the store | Every one → **none** |
| Stale memory | How often the outdated preference wins | 0.33 → **roughly never** |
| Deletion | Gone from database and search within 60 seconds | — → **passes** |
| The comparison | Full Deliverable 3 test, re-run against the baseline | — → **reported** |

**A milestone that does not clear its gate is not finished** — however good the demo looks. That rule is the whole point of having measured the baseline in the first place.
