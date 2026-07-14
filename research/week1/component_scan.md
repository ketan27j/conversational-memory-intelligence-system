# Week 1 — Component Scan

**Deliverable:** 2 (Research-to-Design Scan)
**Author:** Ketan Juikar
**Week of:** June 2026

---

## Where I started this week

I do not have a full system design yet — that comes in Deliverable 4. So when I say "my current design," I mean the capabilities I worked out in Deliverable 1.

Looking at those, three parts of the system were the weakest, and that is where I spent my time.

1. **Search** — my F4 (exact-fact miss). My first plan was to search only by meaning. I am not confident that meaning alone finds the right memory.
2. **Ranking and contradictions** — my F3 (stale memory). My first plan was a simple rule: newer and more confident wins. I do not know whether that is enough when a user changes their mind.
3. **Testing** — my C14 (repeatable testing). I claimed all these failures in Deliverable 1, but I have no way to *measure* them yet. And without a way to measure, every decision below is just my opinion.

I took a quick look at the other parts — pulling facts out, storage, forgetting, keeping users apart — but I did not go deep on them this week.

---

## What I found

### Search

**Where I looked:** Mem0's *State of Agent Memory 2026*; the Hindsight system (through the Vectorize and Atlan round-ups); Particula's comparison of the different frameworks.

**What they do:** Instead of searching one way, they search several ways at the same time and then combine the results.

Mem0's April 2026 redesign runs three searches in parallel — by meaning, by exact keyword, and by matching names and entities — then puts the scores on a common scale and merges them into one. Hindsight goes further: it runs four searches at once, and then passes the results through a second, more careful model that re-scores each one properly against the question.

**Why it matters to me:** This attacks my F4 (exact-fact miss) head on. The field's message is blunt — searching by meaning alone confuses "sounds related" with "actually answers the question." And the things that have to be exactly right, like a version number or a client name, are exactly what it misses.

This was the single most repeated finding across everything I read this week.

### Ranking and contradictions

**Where I looked:** Zep's architecture notes; Particula's breakdown of the problem; the "knowledge update" questions inside the LongMemEval benchmark.

**What they do:** Zep stores **two dates** on every fact — when it was actually true in the real world, and when the system recorded it.

So when a user says "I moved from London to Tokyo," the system does not just keep both facts and get confused. It knows the London fact stopped being true, and it returns Tokyo. That mechanism is why Zep scores 63.8% while Mem0 scores 49.0% on the same benchmark — a 15-point gap, on exactly the ability to handle facts that change.

**Why it matters to me:** This is the named, properly measured version of my F3 (stale memory). It also raises an uncomfortable question I have to answer honestly: is my simple "newer and more confident wins" rule a cheap version of this that works well enough? Or is it a shortcut that will quietly break?

### Testing

**Where I looked:** Mem0's *AI Memory Benchmarks 2026*; the LongMemEval paper (Wu et al., 2024); the LoCoMo paper (Maharana et al., 2024).

**What they do:** Three shared benchmarks now exist. A benchmark here means a fixed set of long conversations with questions attached, so different systems can be compared fairly on the same test.

- **LongMemEval** — 500 questions across about 40 conversations. It scores five different abilities: pulling information out, reasoning across many sessions, reasoning about time, handling facts that change, and knowing when to say "I don't know."
- **LoCoMo** — about 10 long conversations and 1,540 questions. It covers simple lookups, questions needing several steps, questions about time, and deliberately unanswerable ones.
- **BEAM** — pushes the same idea towards much longer conversations.

All three are scored by using an AI model as the judge, with published prompts so everyone judges the same way.

**Why it matters to me:** This is the missing piece, and it is better than I expected. The benchmark's *question categories* line up almost one-to-one with my failures:

- Their "time" and "knowledge update" questions = my F3 (stale memory).
- Their "I don't know" questions = my cold-start case.
- Their multi-step questions = the search quality I worried about in F4 (exact-fact miss).

---

## Everything I picked up, before narrowing it down

| # | The idea | Where it came from | My first reaction |
|---|----------|--------------------|-------------------|
| a | Search several ways at once — by meaning, by exact keyword, and by entity | Mem0 (April 2026) | Strong fit for F4 (exact-fact miss) |
| b | Pass the results through a second model that re-scores them | Hindsight | Strong fit for F4, but it will cost speed |
| c | Store two dates on every fact — when it was true, and when it was recorded | Zep | The best answer to F3 (stale memory), but heavy to build |
| d | Use the LongMemEval and LoCoMo benchmarks as my test set | Wu / Maharana | This is what makes every other decision possible |
| e | Pull clean facts out of a conversation in a single pass | Mem0 (April 2026) | A cheap way to stop junk getting in — fits F2 (memory pollution) |
| f | Let the system *learn* what to forget, rather than following a fixed rule | Memory-R1, DeltaMem | Interesting, but almost certainly far too much for a first version |
| g | Store entities right next to the memories, instead of running a separate graph database | Mem0 (April 2026) | A cheaper way to get the entity signal |

I took five of these forward for a proper look — **a, b, c, d, and e**. They are examined in `idea_evaluation_matrix.md`.

I rejected **f** straight away: a first version does not need a machine-learned forgetting policy when a simple formula will do. And I folded **g** into my thinking on **c**.

---

## The honest finding of the week

I had been asking the wrong question first.

I went in treating search and ranking as the priority. But I cannot actually judge either of them. Every claim about whether searching several ways helps, or whether storing two dates helps, is just an opinion until I can score it on a real test.

So the most valuable thing I can do this week is not to pick a clever search trick. It is to adopt the **way of measuring** that lets me judge the search tricks at all.

That is the change I take to the design review in `design_opportunities.pdf`.
