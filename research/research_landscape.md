# Research Landscape — Conversational Memory Intelligence System

**Deliverable:** 2 (Research-to-Design Scan) — updated every week
**Owner:** Ketan Juikar
**Last updated:** Week 1, June 2026

---

## How I use this file

This is a living map, not a one-time list.

Each row is one part of the system. For each part I note the papers the handbook gave me as a starting point, the newer work I have found, and whether there is still a gap.

The handbook's papers are the floor, not the ceiling. I add new work when it answers a real requirement or a real failure. I ignore things that are only popular.

Each part of the system is marked:

- **[GAP]** — Deliverable 1 left this weak or uncertain. This is where I spend my time.
- **[WATCH]** — fine for now, but the field is moving fast here.
- **[STABLE]** — the starting papers are enough.

---

## What changed in the field, in plain terms

When the handbook was written, memory for AI assistants was mostly "just put everything in a vector database." That is no longer true. It is now a real field, with its own benchmarks, its own research, and a handful of dedicated systems — Mem0, Zep, Letta, Cognee, and Hindsight, plus some closed commercial ones.

Two problems separate the serious systems from the demos. Both of them are mine, from Deliverable 1:

1. **Old facts never get replaced.** When a user changes their mind, the old fact looks just as similar to the question as the new one, so it wins just as often. This is my F3 (stale memory).
2. **Search confuses "similar" with "useful."** Meaning-based search finds things that sound related but miss the exact name or number you actually asked for. This is my F4 (exact-fact miss).

The field also settled on three standard benchmarks — LoCoMo, LongMemEval, and BEAM. These are shared test sets of long conversations with questions attached, so different systems can be compared fairly. That finally gives me a way to *measure* the failures that Deliverable 1 could only claim.

---

## The component map

| Part of the system | Starting papers (from the handbook) | Newer work I found (2026) | Status |
|--------------------|-------------------------------------|---------------------------|--------|
| How memory is represented | Memory Networks; End-to-End Memory Networks; Neural Turing Machines | Splitting memory into layers and types is now standard. Letta keeps a small always-loaded core, a searchable middle layer, and a deep archive. Mem0 separates memories by user, by session, and by agent. | [STABLE] |
| Handling long context | Attention Is All You Need; long-context research | Models still lose track of things buried in the middle of a long input, even with a million tokens available. So a bigger window is not a substitute for real memory. | [WATCH] |
| Deciding what to store | Conversational memory and information-extraction research | Mem0 now pulls clean facts out of a conversation in a single pass (April 2026), rather than storing the raw transcript. Much cheaper, and far less junk. | **[GAP]** — my F2 (memory pollution) |
| Search | Retrieval-Augmented Generation; RETRO; Memorizing Transformers | Searching several ways at once — by meaning, by exact keyword, and by matching names and entities — then combining the scores. Hindsight goes further and runs four searches in parallel, then passes the results through a second model that re-scores them properly. | **[GAP]** — my F4 (exact-fact miss) |
| Storage and indexing | FAISS; HNSW | PostgreSQL with the pgvector extension is still the practical choice for most teams. And instead of running a separate graph database, systems are now storing the entities directly alongside the memories. | [STABLE] |
| Ranking and contradictions | Generative Agents; learning-to-rank research | Zep stores two dates on every fact: when it was actually true, and when the system recorded it. So "moved from London to Tokyo" resolves properly to the current answer, instead of returning both and confusing the model. | **[GAP]** — my F3 (stale memory) |
| Building the context | MemGPT; long-context systems | Token cost is now a headline number that systems compete on. Mem0 reports using about 7,000 tokens per question, compared with about 26,000 for simply stuffing in the whole conversation. | [WATCH] |
| Forgetting and lifecycle | Generative Agents; MemGPT; continual learning | Some systems (Memory-R1, DeltaMem) now *learn* what to keep, update, and forget, instead of following a fixed rule written by a human. | [WATCH] |
| Testing and monitoring | Search and agent evaluation research | Three benchmarks are now standard: **LoCoMo**, **LongMemEval**, and **BEAM**. They are scored by using an AI model as the judge, with published prompts. Their question categories line up almost exactly with my failures. | **[GAP]** — my C14 (repeatable testing) |
| Privacy and keeping users apart | Privacy-preserving search; unlearning; multi-user research | Systems are appearing that keep all data on the user's own machine, driven by new data protection laws. But keeping users apart is still mostly hand-written code, which is exactly where it goes wrong. | [WATCH] — my F5 (cross-tenant leak), F6 (sensitive data) |

---

## Sources I read this week

- Mem0, *State of AI Agent Memory 2026* and *AI Memory Benchmarks 2026* (mem0.ai/blog) — their redesigned search, and an overview of the benchmarks.
- Mem0's research paper, ECAI 2025 (arXiv:2504.19413) — the first broad head-to-head comparison of ten systems.
- LongMemEval (Wu et al., 2024) and LoCoMo (Maharana et al., 2024) — what the benchmarks actually test.
- Particula, *Agent Memory Frameworks Tested* — the results gap between systems (Zep scored 63.8%, Mem0 scored 49.0%), and a useful way of breaking the problem into three parts: pulling facts out, finding them again, and replacing the ones that change.
- Round-ups from Vectorize, Atlan, TECHSY, and Fountaincity (2026) — how each system is built, and what it trades off.

---

## Things to look at again next week

1. **Systems that learn what to forget** (Memory-R1, DeltaMem). Could this replace my hand-written forgetting rule? Or is it far too much machinery for a first version?
2. **The BEAM benchmark at a million tokens.** Accuracy apparently drops about 25% when the scale goes up tenfold. That suggests handling time and change is still an unsolved problem, and it is worth knowing before I commit to a forgetting design.
3. **Systems that keep data on the user's own machine.** Directly relevant if I aim this at a regulated bank rather than a small product.
