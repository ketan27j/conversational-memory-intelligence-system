# Wiki Index — conversational-memory-intelligence-system

The project knowledge base. Same schema as the agentic-swe-kit wiki: concept pages in `concepts/`,
each with frontmatter and ≥2 `[[wikilinks]]`. The L3 RESEARCH loop writes here; G0 reads here first.

> **Read this file before any milestone (G0 step 1).** Pick candidate pages by name-matching the
> milestone's nouns, then drill in. The wiki is what prevents rebuilding work that already exists.

## Entities (the things this system has)
<!-- - [[concepts/<Entity>]] — one-line summary -->

## Concepts (how it works)
<!-- - [[concepts/<Concept>]] — one-line summary -->

## Sources (research distilled by L3)
<!-- - [[concepts/<source-slug>]] — one-line summary | filed <date> -->

## Seeded from agentic-swe-kit
Relevant global concept pages for this project's phases (pointers only — read on demand):
- $AGENTIC_SWE_WIKI_ROOT/llmops-ai-agents/concepts/RAG-Architecture.md — hybrid retrieval, reranking, citation grounding (M2 search/ranking)
- $AGENTIC_SWE_WIKI_ROOT/llmops-ai-agents/concepts/Conversational-Agents.md — memory-in-the-loop conversational design (whole project)
- $AGENTIC_SWE_WIKI_ROOT/llmops-ai-agents/concepts/Evaluation-Frameworks.md — golden dataset, LLM-as-judge calibration (M5, C14)
- $AGENTIC_SWE_WIKI_ROOT/llmops-ai-agents/concepts/Observability-and-Cost-Control.md — per-write/per-retrieval cost + latency tracking (M5, C12)
- $AGENTIC_SWE_WIKI_ROOT/security-engineering/concepts/Threat-Modeling.md — adversary categories, trust boundaries (already applied in design/threat_model.md)
- $AGENTIC_SWE_WIKI_ROOT/security-engineering/concepts/Access-Control.md — row-level tenant isolation (M0, INV-1)
- $AGENTIC_SWE_WIKI_ROOT/security-engineering/concepts/Privacy-and-Inference-Control.md — secrets/PII filtering before write (M1, INV-2)
- $AGENTIC_SWE_WIKI_ROOT/designing-data-intensive-applications/concepts/Conflict-Resolution.md — contradiction handling, newer-wins-with-history (M3, C8)
- $AGENTIC_SWE_WIKI_ROOT/designing-data-intensive-applications/concepts/Storage-Engines.md — one-Postgres-database layout choice (ADR-003, M0)
