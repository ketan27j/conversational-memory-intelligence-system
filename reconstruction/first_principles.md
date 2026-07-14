# First Principles — What the System Must Do

**Project:** Conversational Memory Intelligence System
**Deliverable:** 1 (Problem Reconstruction)
**Author:** Ketan Juikar

---

## The one sentence everything hangs from

Imagine an assistant with no memory. In one session I tell it I like short answers, and that I am migrating a .NET codebase to Java. In the next session it has forgotten both. The system pays the same cost every time: the user has to re-establish who they are, what they want, and how they like to be spoken to.

So memory exists to solve exactly one problem: **stop losing information between conversations.**

That one sentence already rules out the most common mistake, which is treating memory as a dumping ground for everything the user ever said. Memory is not storage. A database stores everything. A memory system stores only the things that will improve future answers. The important word is **selective**.

I think about this the same way I judge any AI proposal at the bank: *is this even worth doing, and is this even worth keeping?* So the first thing standing in front of the store is not a write. It is a decision about whether to write at all.

What follows is each capability the system needs, and the specific failure that forces it. I am deriving these, not picking features off a list.

---

## C1 — Memory that survives between sessions
**Fixes:** F0 (stateless calls).
**The principle.** If the cost of setting up context is paid on every interaction, then context has to carry across interactions.
**What this means.** A store that outlives the conversation and is tied to a user, so anything learned today is available tomorrow.

## C2 — Keep only what matters, don't replay everything
**Fixes:** F1 (history replay, which overflows the window and costs too much).
**The principle.** The context window is limited and you pay for it. Carrying the whole past is not memory. It is a bill that grows as the relationship gets more valuable.
**What this means.** Store short, clean facts instead of raw transcripts, and inject only what is relevant, inside a fixed token budget. Memory should make the context *smaller*, not bigger.

## C3 — A write gate that decides what is worth keeping
**Fixes:** F2 (memory pollution).
**The principle.** Anything that accumulates needs a policy for what gets in. Decide what to keep before deciding where to put it.
**What this means.** A checker sits between "we noticed a fact" and "we saved a fact." It scores each candidate on whether it will help a future conversation, and drops the ones that will not. "I use PostgreSQL" gets in. "I had dosa today" does not.

> **A note from my day job.** In an early version this checker can be an AI model asked "would this help a future conversation, yes or no, and how important is it from 1 to 10?" But the same memory must score the same way every time, and that consistency is exactly what an AI model does not give you.
>
> So at volume, the checker should become a small trained classifier instead. This is the same call I make every week as an AI catalyst: if the output must be identical for identical input — a score, a category, a ranking — that is a job for classic machine learning, not for a language model. I am putting that decision in the design from day one, because I have watched teams discover it the expensive way.

## C4 — Different types of memory, with different rules
**Fixes:** F3 (stale memory), and supports C2.
**The principle.** People do not store all memories the same way, and neither should we. Different kinds of memory last for different lengths of time and get updated differently.
**What this means.** Split memory into four types, and let the type decide the rules:

- **Events** (episodic) — things that happened, with a date. "Launched a product in Q2." Only ever added, never changed.
- **Facts** (semantic) — stable truths. "Knows Python." "Works in machine learning." Can be overwritten and de-duplicated.
- **Preferences** (procedural) — how the user wants to be answered. "Likes short replies." Small in number, high priority when retrieved.
- **Live conversation** (working) — the current chat. Not saved by default. It gets promoted only if it proves useful.

This is not trivia. It is the actual database schema, and the promotion path (live conversation → session → long-term) is the "keep only what matters" principle written as a data flow.

## C5 — A proper record, not a blob of text
**Fixes:** F3 (stale memory), F6 (sensitive data), and it is what makes forgetting possible at all.
**The principle.** What lands in the store is a structured record, because every later decision — ranking, forgetting, security, explaining itself — reads one of its fields.
**What this means.** Each memory carries at least: an ID, the user it belongs to, its type, the content, an importance score, a confidence score, where it came from, and when it was created and updated.

Three of these earn their place by making a later decision possible. **Importance** and **confidence** let the system tell the difference between "is definitely building CommentHook" and "might be thinking about moving cities." **Source** lets it answer the question "why do you think that?"

## C6 — Ranking that uses more than similarity
**Fixes:** F3 (stale memory), and it is the heart of good retrieval.
**The principle.** Relevance is a scoring problem, not a lookup. Name your signals, weight them, and let the weights be tuned.
**What this means.** Score every candidate on how well it matches the question, how recent it is, how often it has been used, and how important it is. Then take the best few. A starting formula:

```
score = 0.4·similarity + 0.2·recency + 0.2·frequency + 0.2·importance
```

Those weights are a starting guess to be tuned against a test set, not a law.

## C7 — Hybrid search
**Fixes:** F4 (exact-fact miss).
**The principle.** Three weak signals combine into one strong answer. Each search method catches what the others miss.
**What this means.** Search three ways at once — by meaning (vector search), by exact words (keyword search, which catches names and version numbers), and by linked entities — then combine the scores. This is the direct fix for "the memory is there but we cannot find it."

## C8 — Deciding which fact wins when two disagree
**Fixes:** F3 (stale memory, the contradictory case).
**The principle.** When a new memory contradicts an old one, the system has to decide which is true *now*, instead of keeping both and confusing itself.
**What this means.** When writing a new memory, compare it against existing memories on the same subject. The default rule: newer and more confident usually wins. But always keep the old memory's history, so the change can be audited. Sometimes both are true and both are kept. Sometimes one was a mistake, and the more confident one wins.

## C9 — Forgetting
**Fixes:** F7 (memory explosion).
**The principle.** Anything that accumulates with no forgetting policy grows without limit. Design the forgetting at the same time as the remembering.
**What this means.** Each memory carries a weight that fades over time unless something refreshes it:

```
weight = importance × recency × how often it has been useful
```

Every time a memory is retrieved and actually helps, its weight is topped up. So useful memories stay alive, and stale ones sink on their own. A nightly background job (never on the live request path) reduces the weights and archives anything below a floor. **Archived, not deleted** — because the user might still ask, and the history has to survive.

## C10 — Users can never see each other's memories
**Fixes:** F5 (cross-tenant leak). **Non-negotiable.**
**The principle.** Most memory systems are really security systems wearing a friendly face. Return user A's memory to user B once, and it is over.
**What this means.** Every read is limited to one user, and that limit is enforced *inside the database*, not in application code, so that a forgotten filter cannot leak anything. Separation must be a property of the store, not something developers are trusted to remember.

## C11 — Block sensitive data, and delete for real
**Fixes:** F6 (sensitive data retained).
**The principle.** Keep dangerous data out of the store completely, and make deletion actually mean deletion.
**What this means.** A filter checks every candidate before it is written and blocks secrets, keys, and card numbers. A deletion request removes the memory from both the database and the search index, within a stated time window. Anything sensitive that is stored is encrypted.

## C12 — Watching whether it works
**Fixes:** the blind spot behind everything above. You cannot fix what you cannot see.
**The principle.** When memory goes wrong, users lose trust immediately. You want to learn that from a dashboard, not from complaints.
**What this means.** Measure four things — is memory being used (how often it is retrieved), is it right (how often users correct it), how fast is it (target: under about 100 milliseconds), and what does it cost (per write and per retrieval).

This is the one area where my background genuinely helps. I have run weekly retraining and ELK-based monitoring for the bank's fraud models, so watching a production system like this is familiar ground, not new ground.

## C13 — If memory breaks, still answer
**Fixes:** the reliability gap that runs under all of the above.
**The principle.** The system should degrade to slow-but-correct, never fast-but-wrong. The worst failure is a confident wrong answer.
**What this means.** If the memory store is down or slow, the lookup times out and the assistant answers *without* memory rather than failing the whole response. Memory is an enhancement to the conversation. It must never be a single point of failure for it.

## C14 — Testing you can repeat
**Fixes:** the underlying requirement that makes Deliverables 3 and 6 possible at all.
**The principle.** You cannot ship what you cannot measure, and you cannot claim an improvement you cannot reproduce.
**What this means.** A fixed test set and a fixed random seed, with measurements at the component level (search precision, ranking quality) and end to end (answer quality, speed, cost). This lets the final design be compared against the naive baseline. The handbook makes that comparison a gate, and it is the right gate.

---

## The minimum system, in one breath

Taken together, the failures force a system that: **decides whether to write (C3), stores proper typed records (C4, C5), finds them using several signals (C6, C7), settles contradictions (C8), forgets on a schedule (C9), keeps users separate and protects their data (C10, C11), watches itself (C12), survives its own outages (C13), and can be measured (C14) — all so it can do the one thing it exists for: stop losing information between conversations (C1, C2).**

Nothing on that list is a feature I wanted. Every line is a failure I could not design around any other way.

---

## Open questions that will shape the design

I am deliberately *not* settling these here. They belong in the system design (Deliverable 4), once the baseline experiment (Deliverable 3) has given me real numbers.

1. **When to promote.** When does a fact from the live conversation get promoted to long-term memory? After it proves useful once, or twice?
2. **Where the write gate runs.** On the live request path (which slows down capture), or in the background (which risks a short window where a fact is not yet saved)?
3. **When the write gate graduates** from an AI judge to a trained classifier. What volume or cost justifies the switch, and how do I get training labels without circular reasoning?
4. **Ranking weights.** Fixed, or learned? And how do I tune them honestly without a labelled set of "correct" answers?
5. **Entity graph.** Is it needed for the first version, or is it a second-version component?
6. **Deletion speed.** How fast must a deleted memory disappear from search — instantly, or within a stated limit?
7. **User separation strategy.** Row-level security in one shared database, versus a separate schema or database per user. The right answer for a small product (CommentHook) and for a regulated bank may not be the same, and I want to be explicit about which one I am building for.
8. **Storage layout.** One table split by type, or physically separate stores with different indexes?

Each of these becomes a decision record in Deliverable 4, with options, a decision, and a note on what would make me revisit it.
