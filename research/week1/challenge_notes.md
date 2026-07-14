# Week 1 — Challenge Notes

**Deliverable:** 2 (Research-to-Design Scan)
**Author:** Ketan Juikar
**Week of:** June 2026

---

## What this document is

The handbook wants this file to record the **real** technical challenge from the live 20-minute design review — the strongest objections people raised, the answers that changed after the discussion, and what was finally decided about each idea.

I cannot invent an audience. So this file has two parts:

- **Part A — The challenges I expect (my preparation).** The objections I think will come, written *before* the review, with my current answer. This is preparation. It is not evidence.
- **Part B — The real challenges (filled in live).** Empty until I actually present. This is the part that counts.

I am keeping them clearly separate, so that I do not pass off my own preparation as if it were the review.

---

## Part A — The challenges I expect

The handbook lists seven things a good challenge should push on. Here is my answer to each, for this week's proposal: adopt the benchmarks, adopt searching several ways at once, and postpone the two-date graph.

### 1. Which real problem does this idea solve?

Adopting the benchmarks solves the problem underneath everything else: all my Deliverable 1 failures are currently claimed, not measured.

Searching several ways at once solves F4 (exact-fact miss).

Postponing the graph means F3 (stale memory) still gets addressed — just with a cheaper rule first.

### 2. Does the evidence actually apply to my situation?

**The objection I expect:** "Zep's 63.8% against Mem0's 49.0% was measured on GPT-4o, with conversations of about 115,000 tokens. Your first version is much smaller, and may run on local models. Does that 15-point gap even apply to you?"

**My answer:** It may not transfer cleanly. That is *exactly* why I postponed the graph instead of adopting it.

The gap tells me F3 (stale memory) is a real problem worth planning for. It does not tell me the graph is worth building for *my* workload. That is what the knowledge-update test is for.

### 3. What has to stay true for this to work?

That the benchmark's questions are a fair stand-in for my real traffic — preferences that change, and project context.

If my actual usage turns out to be dominated by something the benchmark barely tests, then the benchmark could quietly mislead me. To guard against that, I will sanity-check against a small hand-built set of questions taken from my own CommentHook and migration transcripts.

### 4. Would something simpler give the same benefit?

**The objection I expect:** "Why search three ways? Wouldn't meaning-based search plus a recency boost get you most of the way there?"

**My answer:** Possibly, for preferences. But not for exact facts — names, version numbers — where meaning-based search is structurally weak. That is the specific gap that keyword and entity search fills.

Rather than argue about it, I will let the benchmark decide the weights.

### 5. What risk does it add?

- Combining several searches means putting their scores on a common scale, which is fiddly.
- Re-scoring with a second model costs speed. I have flagged that as the thing to measure, not to assume.
- Using an AI model as the judge adds randomness and cost. I handle that by fixing the judge and using a smaller slice of the test set.

### 6. How will it be tested before I build it in?

The two adopted ideas get tested by the benchmark itself.

The two prototypes have specific, named experiments waiting in the backlog.

The graph is gated on the knowledge-update result.

### 7. What would make me reject or reverse this?

- Reverse the multi-way search if it does not beat meaning-only search, even after the weights are tuned.
- Reject the second re-scoring model if it blows the speed budget without a real accuracy gain.
- Keep the graph postponed unless the simple rule fails the knowledge-update test.

---

## Part B — The real challenges from the review (fill in after presenting)

> Record here, during or right after the live review: the strongest objection raised, who raised it, my answer, whether my position actually **changed**, and what was finally decided.

**Challenge 1.**
- Raised by:
- The objection:
- My answer:
- Did my position change? (yes / no — and how):
- What was finally decided:

**Challenge 2.**
- Raised by:
- The objection:
- My answer:
- Did my position change?:
- What was finally decided:

**Challenge 3.**
- Raised by:
- The objection:
- My answer:
- Did my position change?:
- What was finally decided:

**What changed in my backlog after the review:**

> For example: "moved the second re-scoring model to rejected, after the objection about speed," or "promoted the two-date graph from postponed to prototype, after being challenged on whether the evidence transfers."
