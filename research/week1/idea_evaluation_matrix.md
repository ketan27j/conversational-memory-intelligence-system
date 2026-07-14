# Week 1 — Idea Evaluation Matrix

**Deliverable:** 2 (Research-to-Design Scan)
**Author:** Ketan Juikar
**Week of:** June 2026

Five ideas, each checked properly. For every one I ask: what problem does it solve, how does it work, what did the source *actually prove*, what would it cost me to build, what risk does it add — and then I make a clear decision.

Every idea is tied to a failure (F) or a capability (C) from Deliverable 1.

For each idea I also keep three things separate, which matters more than it sounds:

- what the source genuinely **proved**
- what its authors **believe** on top of that
- what **I** propose to do about it

---

## The five decisions at a glance

| Idea | What it answers | Part of the system | Decision | Why, in one line |
|------|-----------------|--------------------|----------|------------------|
| d. Use the LongMemEval and LoCoMo benchmarks as my test set | C14 (repeatable testing) | Testing | **ADOPT** | Nothing else can be judged without it |
| a. Search several ways at once | F4 (exact-fact miss) | Search | **ADOPT** | Confirms my plan, and gives me a concrete recipe |
| b. Re-score the results with a second model | F4 (exact-fact miss) | Search | **PROTOTYPE** | Probably more accurate, but I must measure the speed cost |
| e. Pull facts out in a single pass | F2 (memory pollution) | Deciding what to store | **PROTOTYPE** | Cheap way to keep junk out, but unproven on my data |
| c. Store two dates on every fact | F3 (stale memory) | Ranking | **DEFER** | The best answer, but heavy — try the simple rule first |

---

## d. Use the benchmarks as my test set — ADOPT

**The problem it solves.** My C14 (repeatable testing). And the deeper problem underneath: every failure I described in Deliverable 1 is currently *claimed*, not measured.

**How it works.** A benchmark here means a fixed set of long conversations with questions attached, so different systems can be compared fairly on the same test.

LongMemEval scores five abilities: pulling information out, reasoning across many sessions, reasoning about time, handling facts that change, and knowing when to say "I don't know." LoCoMo adds simple lookups, questions needing several steps, and deliberately unanswerable ones. Both are scored by an AI model acting as judge, using published prompts.

**What the sources proved.** Every serious system in 2026 publishes its scores against these. And the consistent finding is that even good systems still fall short of human performance on long conversations. That is direct evidence that the problem is real and not yet solved.

**What their authors believe.** That these benchmarks are now the bar for the whole field.

**What I propose.** Adopt LongMemEval as my main test set for Deliverables 3 and 6, because its categories map onto my failures:

- Its time and knowledge-update questions are my F3 (stale memory).
- Its "I don't know" questions are my cold-start case.
- Its multi-session questions are the whole premise behind F0 (stateless calls) and F1 (history replay).

Use LoCoMo as a second opinion.

**What it costs me.** Low to moderate. The test sets are public. The work is wiring up a test runner and an AI judge. It changes nothing about the architecture.

**The risk.** Using an AI model as the judge adds its own randomness. I will fix which model does the judging and which prompt it uses, and report both. Also, these conversations are much larger than what my first version targets, so I may need to use a smaller slice of them.

**Decision: ADOPT.** This is the move that unlocks the whole project. That is why it is also the change I take to the design review.

---

## a. Search several ways at once — ADOPT

**The problem it solves.** My F4 (exact-fact miss). It also strengthens C6 (multi-signal ranking) and C7 (hybrid search).

**How it works.** Run three searches in parallel — by meaning, by exact keyword, and by matching names and entities. Put the three scores onto a common scale, then merge them into one. This is Mem0's April 2026 redesign.

Mem0 also did something clever: instead of running a separate graph database, they pull entities out when a memory is written and store them right alongside. At question time, entities found in the question boost the matching memories.

**What the source proved.** Mem0 reports this as part of a redesign that cut token use sharply — about 7,000 tokens per question, compared with about 26,000 for stuffing in the whole conversation.

**What their authors believe.** That searching several ways reliably beats searching one way. This is the vendor's own claim about their own product, so I treat it with some caution.

**What I propose.** This confirms the hybrid search I had already sketched. I adopt the *shape* of it — search in parallel, put scores on a common scale, merge — and I adopt the entity trick as a cheaper alternative to standing up a separate graph database.

**What it costs me.** Moderate. PostgreSQL can do keyword search right next to meaning-based search, in the same database. Pulling out entities is a small addition to the extraction step.

**The risk.** Putting scores from three very different kinds of search onto a common scale is fiddly, and easy to get subtly wrong. The weights will need real tuning against the test set from idea (d).

**Decision: ADOPT** the pattern. Tune the weights with real measurements once the test set exists.

---

## b. Re-score the results with a second model — PROTOTYPE

**The problem it solves.** F4 (exact-fact miss) — specifically, how good the top few results are.

**How it works.** The first search is cheap and returns a pool of maybe 20 to 50 candidates. Then a second, slower, more careful model looks at each candidate *together with* the question and scores it properly. Hindsight does this after running its four parallel searches.

**What the source proved.** Hindsight is credited with catching things that single-search systems miss, and the re-scoring step is presented as the reason why.

**What their authors believe.** That the extra step is worth what it costs.

**What I propose.** Prototype it as an optional final step. My constraint is speed — I am targeting under about 100 milliseconds — and a second model pass over 20 to 50 candidates may or may not fit inside that.

**What it costs me.** Moderate. It is an extra model call, sitting on the live request path where the user is waiting.

**The risk.** Speed. This is the classic trade between being more accurate and being slower, and I should not accept it on faith.

**Decision: PROTOTYPE.** The experiment: measure both the accuracy of the top results *and* how long the lookup takes, with and without this step, on the multi-step questions. Adopt only if the accuracy gain is genuinely worth the delay.

---

## e. Pull facts out in a single pass — PROTOTYPE

**The problem it solves.** F2 (memory pollution), and the cost constraint.

**How it works.** Pull the useful facts out of a conversation turn in one go, rather than storing the raw transcript or making several separate model calls. The point is simple: a raw transcript is a log. Useful memory is a handful of clean facts.

**What the source proved.** Mem0 presents this as the basis of their token savings.

**What their authors believe.** That one pass is both cheaper and good enough.

**What I propose.** Prototype it as the thing that feeds my write gate. It does *not* replace the gate's keep-or-drop decision. It just makes the candidate cleaner before the decision gets made.

**What it costs me.** Low to moderate. Mostly a matter of how the prompt and the step are structured.

**The risk.** One pass may miss facts that several passes would have caught. That is a trade between catching everything and keeping costs down — and it is measurable, on the information-extraction questions in the benchmark.

**Decision: PROTOTYPE.**

---

## c. Store two dates on every fact — DEFER

**The problem it solves.** F3 (stale memory) — my sharpest failure.

**How it works.** Zep stores facts in a graph where every fact carries two dates: when it was actually true in the real world, and when the system recorded it.

So a change like "moved from London to Tokyo" is modelled properly. The system knows the London fact stopped being true, rather than keeping both and getting confused.

**What the source proved.** Zep scores 63.8% against Mem0's 49.0% on the same benchmark. That is a 15-point gap, on exactly the ability to handle facts that change. This is real, independently reported evidence — not just a vendor bragging about itself.

**What their authors believe.** That a time-aware graph is the right foundation for facts that change.

**What I propose.** This is genuinely better than my plan. But it is heavy: a whole graph database, time modelling, and the delay that graph processing adds to every question.

Before I take on all that complexity, I want to know how far my *simpler* design actually gets. That simpler design is: weight recency in the ranking (C6), plus a rule for contradictions (C8) — newer and more confident wins, and keep the old fact for the audit trail.

My hypothesis is that the simple rule closes most of the gap on **preferences**, which is my actual use case, even if it loses on complicated multi-step reasoning about time.

**What it costs me.** High. A new database, and a new processing path.

**The risk.** Building far too much for a first version. The handbook explicitly warns against adopting an idea just because it scores well on a benchmark.

**Decision: DEFER to version 2.**

But it is now the top item on my backlog, and it is gated on a specific test. If my simple rule scores badly on the knowledge-update questions, then the two-date graph is the planned response.

I am not rejecting it. I am refusing to build it before the cheaper option has been shown to fail.

---

## One thing that cuts across all of these

Several of these ideas — a, e, and the contradiction rule behind c — run through my **write gate**, the thing that decides what is worth storing.

The pattern in the field matches the position I took in Deliverable 1: pulling facts out and judging them starts as a job for an AI model, and moves towards cheaper, more predictable scoring as the volume grows.

I am keeping that graduation path explicit in the backlog, rather than committing to it now.
