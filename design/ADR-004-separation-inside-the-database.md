# ADR-004: Enforce user separation inside the database, not in code

Status: accepted · Date: June 2026

## The situation
Deliverable 3 measured the cross-user leak rate climbing to 0.92 as the store grew. Eleven out of twelve personal questions returned somebody else's memory.

This is the sharpest security failure in the whole project, and the handbook makes it a non-negotiable gate.

## What matters here
- One forgotten filter, in one query, must not be able to leak someone's data.
- Separation cannot depend on every developer remembering to do the right thing, every time, forever.

## The options
1. **Filter in the application code.** Add a user check to every query. This works right up until somebody, someday, forgets one — and then it is a breach.

2. **Let the database enforce it.** PostgreSQL can hold a rule that automatically limits every query to the current user. The database simply will not hand over another user's rows, no matter what the query asks for.

## The decision
Option 2. Every connection declares who the user is, and the database enforces the boundary from there.

Application-level filters stay in place as a second layer — but they are not the thing I am relying on.

## What it costs me
A little extra complexity in how database connections get set up.

In exchange, separation stops being something people have to remember, and becomes a property of the system itself. That is the entire point.

## How I will know it worked
The cross-user attack test has to show **zero** leaks — not few, zero.

And a deliberately unfiltered query has to be refused by the *database*, not caught by application code. That second test is the real one, because it proves the protection lives where it needs to live.

## What would make me revisit this
Only if a hard scale requirement forces me towards giving each user physically separate storage.
