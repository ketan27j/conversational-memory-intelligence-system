# API Contracts — Conversational Memory Intelligence System

**Deliverable:** 4 (System Design) &middot; **Author:** Ketan Juikar

A small, clear set of calls that other systems can make.

Two things are true of every one of them.

First, **the user is always worked out from the login token, never from the message itself.** If an attacker puts someone else's user ID in the body of the request, the server simply ignores it. That is the first rule (INV-1: no user ever sees another user's memory).

Second, **every error has a clear meaning**, so the calling system knows what to do about it. That matters most when memory is unavailable, and the assistant needs to carry on anyway (C13: if memory breaks, the assistant still answers).

---

## Send in a conversation turn

`POST /v1/memories:ingest`

Extraction and the write gate run **in the background**, so this call comes back immediately with a receipt.

But the check for secrets runs **right now, before anything is queued.** That way a password or an API key is never written down anywhere — not in the database, and not even in a queue while it waits to be processed.

**What you send**
```json
{ "session_id": "uuid", "role": "user", "text": "I've switched to spaces for indentation now." }
```

**What comes back**
```json
{ "turn_id": "uuid", "status": "queued", "pii_blocked": false }
```

If a secret was spotted, `pii_blocked` comes back as `true`, and the offending text is thrown away. The audit log records *that* a secret was blocked — never the secret itself. This is C11 (blocking sensitive data), and it fixes F6.

---

## Ask for the relevant memories

`POST /v1/memories:retrieve`

This is the call that builds the assistant's context before it answers.

**What you send**
```json
{ "query": "how does the user like answers written?",
  "token_budget": 512,
  "k_max": 8,
  "rerank": false }
```

**What comes back**
```json
{
  "memories": [
    { "id": "uuid", "type": "preference", "content": "Keep answers short and concise.",
      "score": 0.82, "importance": 8, "confidence": 0.9, "created_at": "..." }
  ],
  "abstained": false,
  "tokens_used": 34,
  "signals": { "semantic": 0.71, "recency": 0.9, "importance": 0.8 }
}
```

Four promises this call makes:

- It will **never** return a memory belonging to someone else (rule INV-1). This fixes F5 (cross-tenant leak).
- It will **never** use more tokens than you allowed (rule INV-3). This is C2 (keep only what matters).
- If nothing is genuinely relevant, it comes back with `abstained: true` and an empty list — an honest "I have nothing useful" instead of a handful of bad guesses (rule INV-6). **This fixes the cold-start failure I measured**, where the naive system guessed every single time.
- When two memories contradict each other, the newer and more confident one comes first (rule INV-5). This fixes F3 (stale memory).

---

## Tell it that a memory is wrong

`POST /v1/memories:feedback`

When a user says "that's wrong" or "that's out of date," this records it. It feeds the measurement of how often the system gets corrected, and it can trigger a memory being replaced.

**What you send**
```json
{ "memory_id": "uuid", "signal": "outdated" }
```
**What comes back** — `{ "superseded": true, "new_status": "superseded" }`

---

## Delete a memory

`DELETE /v1/memories/{id}`

The right to be forgotten. The memory disappears from all reads immediately, and from the search index within 60 seconds (rule INV-4). This is C11.

**What comes back** — `{ "id": "uuid", "status": "deleted", "purge_within_seconds": 60 }`

---

## List a user's memories

`GET /v1/memories`

Shows the user's active memories, a page at a time. This is for inspection and for the monitoring dashboard. It is not used while the user is waiting for an answer.

---

## What each error means

| Code | What went wrong | What the caller should do |
|------|-----------------|---------------------------|
| `400 invalid_request` | The request is malformed, or the token budget is zero or negative | Fix it and try again |
| `401 unauthenticated` | The login token is missing or wrong | Log in again |
| `403 forbidden` | The token is valid, but that memory belongs to someone else | Do not retry |
| `422 pii_rejected` | The whole message was a secret | Do not send it again |
| `429 rate_limited` | Too many requests, too fast | Wait, then retry |
| `503 memory_unavailable` | The memory store is down or struggling | **Answer the user anyway, without memory** (rule INV-7) |

That last one is the most important, and it is deliberate.

Memory is an *enhancement* to a conversation. It is not the conversation. So when the memory store fails, the assistant does not fail with it — it simply answers the question without the extra context. Degrading gracefully is a designed-in behaviour, not an accident.

---

## Changing things safely over time

- The version number is in the address (`/v1`). Within one version, we can only *add* things, never break what already exists. Anything that breaks existing callers gets a new version number.
- Database changes always move forwards, and stay compatible with the previous version for one release. The pattern is: add the new thing, move everything over, then remove the old thing — never all at once.
- Changing the model that generates the meaning fingerprints is a bigger event. The old memories get re-processed in the background, and each fingerprint is tagged with which model made it — so we only ever compare like with like during the changeover.
