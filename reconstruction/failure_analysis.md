# Failure Analysis — Why the Simpler Designs Break

**Project:** Conversational Memory Intelligence System
**Deliverable:** 1 (Problem Reconstruction)
**Author:** Ketan Juikar

---

## How to read this document

At work I tell teams the same thing every week: before you reach for AI, prove that the simple thing fails. So before I design a memory system, I want to do that to myself.

This document takes each simple approach someone might suggest, says what that approach quietly assumes, and then shows the case where the assumption breaks.

Every failure case is marked with how strong the evidence is:

- **[Measured]** — I will prove this with real numbers in the baseline experiment (Deliverable 3).
- **[Assumed]** — a thought experiment, based on how the parts work. Honest, but not yet proven.
- **[Cited]** — backed by a research paper.

I am writing these failures down *before* building the baseline, on purpose. If the baseline does not reproduce them, that is a finding in itself, and the design has to change.

---

## F0 (stateless calls) — the assistant remembers nothing

**The approach.** Treat every request on its own. The assistant sees the current message and nothing else.

**What it assumes.** Every question is self-contained, so the past does not matter.

**Where it breaks.** I am running a long .NET-to-Java migration with an assistant, across many sessions. In session one I explain the code conventions, the placement rules, and the fact that there are no existing tests. In session two, the assistant knows none of it. I explain it all again. Every session, I pay the cost of explaining who I am and what I am doing.

**The impact.** Wasted time, wasted tokens, no personalisation, and an assistant that cannot honour anything I told it yesterday.

**Evidence.** [Assumed] This follows straight from the design. If nothing is saved, nothing can carry forward.

---

## F1 (history replay) — send the whole conversation every time

**The approach.** Fix the problem above by pasting the entire conversation history into every request. "Just give the model everything."

**What it assumes.** The context window is big enough, and cost and speed do not matter.

**Where it breaks.** The model's context window is limited. [Cited] The transformer works against a fixed context budget, and attention cost grows with the square of the input length (Vaswani et al., 2017). So a long project eventually overflows the window, no matter how big that window gets.

Two other things break before that. Speed drops, because the model re-reads the whole history on every turn. And cost rises, because you pay for those tokens every turn. On my migration project a single conversation runs for hours. Replaying it from the top each turn means paying to re-read the same text dozens of times.

**The impact.** The system gets slower and more expensive the longer the relationship lasts. That is the opposite of what we want.

**Evidence.** [Cited] for the context window limit. [Measured] I will record how token usage and response time grow with conversation length in Deliverable 3.

---

## F2 (memory pollution) — storing everything buries the good stuff

**The approach.** Put everything in a vector database and pull back the closest matches. This is the standard naive setup.

**What it assumes.** Storing everything is fine, because search will filter it later. Deciding what to keep is not my problem; ranking is.

**Where it breaks.** If I store every sentence, the store fills with noise. "I use PostgreSQL" and "I had dosa today" sit side by side with equal right to be retrieved. Later, when I ask for design help, the dosa memory is competing for a slot in a limited context budget.

The more I store, the worse search gets, because the useful memories become a smaller share of a bigger pile. A good memory system is mostly a *forgetting* system, and this approach has no forgetting in it at all.

**The impact.** Search quality drops over time. The context fills with irrelevant facts. Answers get worse exactly as the user uses the system more.

**Evidence.** [Assumed] The mechanism is clear from how "closest match" behaves over a growing pile. [Measured] I will track search precision as the store grows in Deliverable 3.

---

## F3 (stale memory) — the system remembers the wrong thing

**The approach.** Same as above. Pull facts out of the conversation and store them as stated.

**What it assumes.** What the user says maps cleanly onto a lasting fact, and the closest match is the right answer.

**Where it breaks.** Two cases, both very common in real conversation:

1. **It misreads what was meant.** The user says "I'm thinking of moving to Bangalore." A naive extractor stores "user lives in Bangalore." Now every future answer is built on something that was never true. This is the same mistake I deal with in fraud alerting at the bank: a signal that *looks* like an event gets treated as the event.

2. **It keeps the outdated preference.** Early on the user says "I prefer detailed explanations." Weeks later they say "keep it short." Both are in the store. With nothing but similarity, and no sense of what is recent, the old preference can keep winning. The assistant keeps over-explaining to someone who explicitly asked it to stop.

**The impact.** The system confidently acts on facts that are wrong or out of date. That is worse than having no memory, because the user trusts it a little less each time.

**Evidence.** [Assumed] Both follow from storing claims with no confidence score, no sense of recency, and no way to handle contradictions. [Measured] Deliverable 3 includes preferences that change over time, and checks whether the old one beats the new one.

---

## F4 (exact-fact miss) — it has the memory but cannot find it

**The approach.** Search only by meaning (vector similarity).

**What it assumes.** Similar meaning always finds the right memory.

**Where it breaks.** Meaning-based search is good with ideas and bad with exact words. Ask "what database does the user use," and it may return "prefers relational databases" while completely missing the actual word "PostgreSQL" that answers the question.

Names, version numbers, prices, client IDs — the things that have to be exactly right — are exactly what meaning-based search is worst at. In a bank, this is not a small miss. A near-match on a regulation name or a counterparty is a wrong answer.

**The impact.** The memory is in the store but never reaches the assistant. The user experiences it as the system "forgetting" something it actually knows.

**Evidence.** [Assumed] This is a well-known limit of vector search, and the standard fix in the research is hybrid search. [Measured] Deliverable 3 includes exact-fact questions and records how often they are missed.

---

## F5 (cross-tenant leak) — one user sees another user's memory

**The approach.** One shared store, search by similarity, with user separation handled somewhere in the application code.

**What it assumes.** Memories are naturally separate, or a filter written in code is enough.

**Where it breaks.** I run CommentHook as a multi-user product. Two users describe similar businesses in similar words. If separation is not enforced by the database itself, one forgotten filter in one query returns user A's memory to user B.

It only has to happen once to be a breach. This is the failure I take most seriously, because it is not a quality problem. It is a security problem wearing a friendly face.

**The impact.** Serious and permanent. One leak destroys trust for both users, and in a paying or regulated setting, it ends the product.

**Evidence.** [Assumed] This is the standard multi-user failure. [Measured] Deliverables 3 and 6 will attack the system with cross-user queries and check that no other user's memory is ever returned. The handbook makes this a non-negotiable gate, and I agree with that.

---

## F6 (sensitive data retained) — secrets get stored forever

**The approach.** Store whatever the conversation contains.

**What it assumes.** Users will not paste anything sensitive, or it does not matter if they do.

**Where it breaks.** Mid-conversation, a user pastes an API key, a card number, or a password to get help with an error. A store-everything system writes it down, indexes it, and now it sits in the store and in the backups indefinitely.

There is also the right-to-be-forgotten case. A user asks to delete a memory. Unless deletion removes it from *both* the database and the search index, it quietly keeps showing up.

**The impact.** A privacy and compliance liability that grows silently, until an audit or an incident exposes it.

**Evidence.** [Assumed] This follows directly from writing everything down with no deletion contract. [Measured] Deliverable 6 will test sensitive-data blocking with both positive and negative cases, and check that deletion really removes a memory from storage and from search within a stated time.

---

## F7 (memory explosion) — the store grows forever

**The approach.** Keep everything forever. Storage is cheap.

**What it assumes.** A store that only grows will stay fast and cheap.

**Where it breaks.** Anything that keeps growing with no expiry policy grows without limit. A user mentioned wanting to learn Kubernetes eighteen months ago and never again. With no forgetting, that memory still competes for retrieval today, and still costs storage and index time. Multiply that across millions of memories and search gets slower, cost climbs, and the context budget gets harder to manage, all at once.

**The impact.** The system gets slower and more expensive over its life, even if nothing else is wrong. That makes it uneconomic at scale.

**Evidence.** [Assumed] This is the unbounded-growth argument. [Measured] Deliverable 3 will record storage growth and search time as the store gets bigger.

---

## Summary — each failure points to something the system must do

| Failure | The broken assumption | What the real system needs |
|---------|-----------------------|----------------------------|
| F0 (stateless calls) | Every question is self-contained | Memory that survives between sessions |
| F1 (history replay) | Window, cost, and speed are free | Keep what matters, don't replay everything |
| F2 (memory pollution) | Storing everything is fine | A gate that decides what is worth keeping |
| F3 (stale memory) | What is said equals a lasting fact | Confidence, recency, conflict handling |
| F4 (exact-fact miss) | Similar meaning equals relevant | Hybrid search (meaning + exact words + entities) |
| F5 (cross-tenant leak) | Users are naturally separate | Separation enforced by the database itself |
| F6 (sensitive data retained) | Nobody pastes secrets | Block sensitive data, and delete for real |
| F7 (memory explosion) | An ever-growing store stays fast | Forgetting, decay, and archiving |

Every capability in `first_principles.md` traces back to a row in this table. I did not start with a list of features I wanted to build. I started with these breakages, and let them tell me what the system has to do.
