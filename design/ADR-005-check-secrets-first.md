# ADR-005: Check for secrets immediately; do everything else in the background

Status: accepted · Date: June 2026

## The situation
Pulling facts out of a conversation and judging whether to keep them both take time, and they sit right where the user is waiting.

Meanwhile, checking for secrets is what stops a password ever being written down.

So the question is: which of these should the user wait for? This settles another open question from Deliverable 1.

## What matters here
- Sending a message should not wait for slow processing.
- A secret must never be saved. Not permanently, and not even briefly.

## The options
1. **Do everything immediately.** Simplest to reason about. But every message the user sends now waits for the extraction to finish.
2. **Do everything in the background.** Fast for the user. But a secret could sit in a queue, in plain text, waiting its turn to be processed. That is unacceptable.
3. **Check for secrets immediately. Do the extraction and judging in the background.**

## The decision
Option 3. The call returns straight away, as soon as the secrets check has run. Everything else happens on a background queue.

## What it costs me
A fact the user just stated is only retrievable once the background work finishes — a short delay.

For conversational memory, that is fine. Nobody expects the assistant to have memorised something the instant they typed it.

What is *not* fine is delaying protection against secrets. So that never gets deferred.

## How I will know it worked
Sending a message stays fast. The secrets tests pass in both directions. And no plain-text secret ever appears in the queue.

## What would make me revisit this
If the background delay creates a visible "it forgot what I just said" problem, then promote the most recent turn into live working memory immediately, and leave the rest in the background.
