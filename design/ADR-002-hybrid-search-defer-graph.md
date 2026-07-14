# ADR-002: Use hybrid search now; postpone the two-date graph

Status: accepted · Date: June 2026

## The situation
Two failures are the hardest to fix.

F4 (exact-fact miss) — the system cannot find a memory it actually has, because it searched only by meaning and missed the exact name.

F3 (stale memory) — the old fact beats the new one, because nothing tells the system which is current.

Deliverable 2 turned up two mechanisms. One is searching several ways at once. The other is Zep's approach of storing two dates on every fact, which scores 63.8% against Mem0's 49.0% on the same benchmark — a real 15-point gap on handling facts that change.

Then Deliverable 3 showed me something useful: keyword matching already solves the exact-fact problem on its own.

## What matters here
- Ship a correct first version, without building far more than I need.
- F3 (stale memory) has to be addressed. The only question is how heavily.

## The options
1. **Search by meaning only.** Simplest. But weak on exact facts, and weak on facts that change.
2. **Hybrid search** — by meaning, by exact keyword, and by matching names, all inside one PostgreSQL database.
3. **Add a two-date graph.** The best answer for facts that change. But it means a whole new database, and graph processing adds delay to every question.

## The decision
Adopt option 2 for the first version. Postpone option 3 behind a named trigger.

## What it costs me
Combining scores from three different kinds of search is fiddly, and the weights need real tuning against the benchmark.

For now, F3 (stale memory) gets handled the cheap way: weight recency in the ranking, and let the newer, more confident memory win.

## How I will know it worked
On the Deliverable 3 test, hybrid search has to push relevant results above 0.20, and push the "old preference wins" rate below 0.33.

And on the benchmark's questions about facts that change, I finally find out whether my simple rule is actually good enough.

## What would make me revisit this
Build the two-date graph if the simple rule fails those questions.

That is a planned response, not a vague maybe. I am not rejecting the graph. I am refusing to build it before the cheaper option has been shown to fail.
