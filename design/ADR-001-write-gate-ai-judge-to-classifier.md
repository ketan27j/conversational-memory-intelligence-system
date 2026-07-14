# ADR-001: Start the write gate as an AI judge, move to a trained classifier later

Status: accepted · Date: June 2026

## The situation
The write gate (C3) is what decides whether something is worth remembering, how important it is, and what type it is.

Deliverable 3 showed why this matters. When you store everything, only 20% of what gets injected is relevant — the other 80% is junk. So this gate is doing real work, and how I build it matters.

This settles one of the open questions left over from Deliverable 1.

## What matters here
- The same memory has to be scored the same way every single time.
- I need to ship something, and I have no training data yet.
- Once volume grows, the cost of every write starts to add up.

## The options
1. **Use an AI model only.** Flexible, and needs no training data. But it gives slightly different answers each time you ask it the same thing, and it costs money on every single write.
2. **Use a trained classifier only.** Cheap, fast, and perfectly consistent. But it needs labelled training data, which I do not have.
3. **Start with an AI model, then graduate.** Use the AI judge now. Log every keep-or-drop decision it makes as a labelled example. Once there is enough data, train a small classifier on those examples and switch over.

## The decision
Option 3.

This is the rule I apply every week as an AI catalyst, now turned on my own system: **if the output has to be identical for identical input — a score, a category, a ranking — that is a job for classic machine learning, not for a language model.**

I have watched teams discover that the expensive way. So I am putting the graduation in the plan from day one.

## What it costs me
Early on I pay more per write, and I accept a little inconsistency. For a first version, that is a fair trade.

The upside: the graduation becomes a real, scheduled milestone — not a vague "we'll clean that up later" that never happens.

## How I will know it worked
With the gate in place, the share of relevant results has to beat the naive baseline of 0.20. I am aiming for above 0.6.

## What would make me revisit this
Move to the classifier when write volume pushes the cost past its threshold — or sooner, if the inconsistency starts showing up as users correcting the system.
