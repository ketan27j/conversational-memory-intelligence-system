# ADR-007: Use a simple forgetting formula; postpone the machine-learned version

Status: accepted · Date: June 2026

## The situation
Deliverable 3 showed the store growing with no limit at all — from 63 memories to 1,935, with nothing ever cleaned up.

Deliverable 2 found systems (Memory-R1, DeltaMem) that actually *learn* what to forget, rather than following a rule a human wrote. I judged that far too much machinery for a first version.

## What matters here
- Growth has to be bounded (C9). A store that only ever grows eventually becomes unaffordable.
- Keep it simple. One person is building this.

## The options
1. **No forgetting at all.** This is exactly the Deliverable 3 failure. Unbounded, and it gets worse forever.
2. **A simple formula.** How alive a memory is = importance × recency × how often it has proved useful. A nightly job archives anything that falls below a floor.
3. **A machine-learned forgetting policy.** Genuinely powerful. But heavy, and it needs training infrastructure I do not have.

## The decision
Option 2, for the first version. A predictable, explainable nightly job.

The nice property: every time a memory is retrieved and actually helps, its score gets topped up. So the useful memories keep themselves alive, and the stale ones sink on their own. I do not have to decide what matters — usage decides it.

## What it costs me
The floor needs tuning, and a badly set floor could archive something still useful.

That is exactly why memories are **archived, not deleted**. They can always be brought back. Getting the floor slightly wrong is recoverable; deleting the wrong thing is not.

## How I will know it worked
The store stays bounded, even under constant writing. And memories that get retrieved often do not get archived by accident.

## What would make me revisit this
Consider a learned policy only if tuning the floor by hand turns into a genuine bottleneck at scale — not before.
