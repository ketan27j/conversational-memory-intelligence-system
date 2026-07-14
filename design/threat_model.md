# Threat Model — Conversational Memory Intelligence System

**Deliverable:** 4 (System Design) &middot; **Author:** Ketan Juikar

A memory system is really a security system wearing a friendly face.

Two of the failures I measured in Deliverable 3 were not quality problems at all. They were security problems.

The cross-user leak reached **0.92** — eleven out of twelve personal questions returned somebody else's memory. And **every single secret** pasted into the conversation was stored, and could be found again.

So this document is not a formality tacked on at the end. It is where the design earns the right to be trusted with anyone's data.

---

## Who is involved, and how far I trust them

| Who | How much I trust them | Why |
|-----|----------------------|-----|
| The end user | Partly | They can type anything at all, including deliberately hostile text. They cannot be relied on to behave. |
| The calling application | Fully — it is logged in | It holds a token, and that token maps to exactly one user. |
| The memory service itself | Fully — this is the core | It is what enforces the separation, blocks the secrets, and writes the audit trail. |
| The background jobs | Fully | Forgetting, summarising, deleting, re-indexing. |
| The database | Fully, and it is encrypted | The separation rules are enforced right here. |

**The line that matters.** Everything entering the memory service carries a user identity that comes from the login token — never from the message body. The boundary between the user and the assistant is the hostile one, and that is where the defences go.

---

## The threats, and what stops each one

| # | The threat | What it looks like in practice | What stops it | Fixes |
|---|-----------|-------------------------------|---------------|-------|
| T1 | **One user reads another's memory** | A question comes back with somebody else's data in it | A user ID on every row, plus a database rule that refuses to hand over another user's rows. No query, however badly written, can get around it. | Rule INV-1. Fixes F5 (the 0.92 leak) |
| T2 | **Secrets get kept** | Someone pastes an API key or a card number to get help with an error | The secrets filter runs **before anything is saved**. The offending text is thrown away. The audit log records *that* something was blocked, never the value. | Rule INV-2. Fixes F6 |
| T3 | **Poisoning the memory** | Hostile text plants a false memory and marks it as very important | The write gate limits how important anything from untrusted text can be. Facts from users never get full confidence. Contradictions are settled by checking against what else we know. | C3, C8 |
| T4 | **Hidden instructions inside a memory** | A stored memory says "ignore all previous instructions and do X" | Retrieved memories are handed to the model clearly labelled as *data*, never as instructions. A memory cannot give the assistant orders. | The context assembly rules |
| T5 | **Deletion that doesn't really delete** | A user deletes a memory, but it keeps appearing in search results | Deletion happens in two steps: excluded from all reads immediately, then removed from the search index within 60 seconds. Reads never return deleted memories, no matter how far behind the index is. | Rule INV-4, C11 |
| T6 | **Fishing for other people's data** | An attacker fires off many questions, watching what comes back | Rate limiting. Plus the rule that the system stays silent when nothing clears the relevance bar — so weak, uncertain matches never leak out as clues. | Rule INV-6 |
| T7 | **Pretending to be someone else** | The caller puts a different user ID in the request body | The server ignores any user ID in the body entirely. It only ever uses the one from the login token. | Rule INV-1 |
| T8 | **Stealing the whole database** | The database itself gets compromised | It is encrypted. And because secrets were never stored in the first place (see T2), there is far less there worth stealing. The audit log flags unusual access patterns. | Layered defence |

---

## The policy on secrets

- **Finding them.** Pattern matching, plus a classifier, looking for keys, tokens, card numbers, national ID numbers, passwords, and random-looking strings that smell like credentials.
- **What we do.** The offending text is kept out of storage entirely. Not hidden behind asterisks and then stored anyway — genuinely never written down. If the whole message is a secret, the request is simply rejected.
- **What we record.** The *kind* of secret that was blocked. Never the value.
- **The rule (INV-2: secrets are never saved).** This gets tested in both directions. A real API key must be blocked. And an innocent phrase like "my key learnings from the project" must *not* be blocked — a filter that is too eager is its own kind of failure.

---

## Proving that users really stay apart

The handbook makes this a non-negotiable gate, and Deliverable 3 showed exactly why. Here is how it gets proven in Deliverable 6:

- **The cross-user attack test.** Ask every question as user A, while user B holds almost identical memories. Then check that not one of B's memories ever comes back. **Target: zero leaks. Not "few." Zero.**
- **The deletion test.** Delete a memory, then immediately try to retrieve it. Check it is gone from reads, and gone from the search index within 60 seconds.
- **The bypass test.** Deliberately try to run a query with no user filter, directly against the database. Check that the *database* refuses it — not that the application code caught it.

That last one is the real test. It proves the separation lives where it needs to live.

---

## The risks I am left with

I am not claiming this is airtight. Two things remain.

**Secret detection is never perfect.** A new kind of credential, in a format nobody has seen, could slip through. I reduce the damage rather than pretend it cannot happen: the database is encrypted, access is audited, and there is a feedback loop to update the patterns when something gets missed.

**A write gate driven by an AI model can be manipulated.** Carefully crafted text could talk it into storing something it should not (threat T3). Moving that gate to a small trained classifier later reduces this surface considerably.

Both of these are reported, not buried. That is the standard the handbook sets, and it is the right one — a threat model that claims no residual risk is a threat model nobody should believe.
