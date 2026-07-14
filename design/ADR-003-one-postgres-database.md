# ADR-003: Use one PostgreSQL database for everything

Status: accepted · Date: June 2026

## The situation
The system needs to search by meaning, search by keyword, match entities, store the memories themselves, and keep users apart.

That could be four different databases. Or it could be one.

This settles two of the open questions from Deliverable 1.

## What matters here
- Keep the running costs low. This is a first version, and one person is running it.
- Keeping users apart has to be enforceable inside the data layer (C10).

## The options
1. **Separate specialist databases** — a managed vector database, a graph database, and a relational database. Each one is genuinely excellent at its own job.

   But that is three systems to run, patch, back up, and secure. And user separation would have to be enforced in all three, which means three chances to get it wrong.

2. **One PostgreSQL database**, using its vector extension for meaning-based search, its built-in text search for keywords, and a simple table for entities.

## The decision
Option 2. One database holds everything, and user separation is enforced in exactly one place.

## What it costs me
PostgreSQL's vector search will not match a dedicated vector database at very large scale. That is a real cost, and I am accepting it knowingly.

In exchange, there is one system to secure, one to back up, and one to reason about.

Deliverable 3 backs this up with a number: at around 2,000 memories, even scanning everything took under a millisecond. A specialist vector database does not yet earn its keep.

## How I will know it worked
Lookups stay under 100 milliseconds even in the slowest cases, across all the store sizes I tested. And user separation passes the cross-user attack test.

## What would make me revisit this
Move the meaning-based search into a dedicated system if PostgreSQL breaks the speed budget at the scale I actually need.
