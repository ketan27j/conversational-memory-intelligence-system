# ADR-006: Keep the second re-scoring model behind a switch until I measure it

Status: proposed · Date: June 2026

## The situation
Deliverable 2 turned up an idea from the Hindsight system. After the first, cheap search returns its candidates, you pass them through a second, slower, more careful model that looks at each candidate *together with* the question and scores it properly.

It is probably more accurate. It definitely costs time — and that time is spent while the user sits waiting.

## What matters here
- Lookups must stay under about 100 milliseconds, even in the slowest cases.
- Accuracy is worth paying for. But not at any price.

## The options
1. **Always use it.** Best accuracy, worst speed.
2. **Never use it.** Cheapest, but leaves accuracy on the table.
3. **Make it optional**, behind a switch, and measure it properly before deciding.

## The decision
Option 3. Ship it turned off. It can be switched on per request. Run the experiment before making it the default.

## What it costs me
One extra code path to maintain.

In exchange, the speed budget stays protected while I gather actual evidence, instead of guessing.

## How I will know it worked
Measure two things — how accurate the top results are, and how long the lookup takes — with and without it, on the multi-step questions.

Turn it on by default only if the accuracy gain genuinely justifies the delay, and only if it stays inside the speed budget.

## What would make me revisit this
Adopt it as the default if it clears that bar. Remove it entirely if it does not. Either answer is a good outcome; what I refuse to do is adopt it on faith.
