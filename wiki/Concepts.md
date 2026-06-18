# Concepts

### Fuzzy 0–9 edges
Each user is a sparse node connected to attributes by edges weighted 0–9 (a fuzzy "membership" strength), stored sparsely as deviations from a population prior.

### Hebbian write (no LLM)
On each event, co-active attributes' edges strengthen via a saturating update — pure arithmetic, no model call. "Fire together, wire together."

### Decay / forgetting
Unreinforced edges fade (ACT-R-style); ones below a floor are dropped. Forgetting keeps the card small and current, and is what lets FERNme track preference **drift**.

### Spreading activation
Retrieval activates the user node + current context and lets activation flow over weighted edges (with lateral inhibition + temporal decay). The brightest nodes are "relevant now" — no per-turn vector search.

### Memory card (three tiers)
- **Card** — top activated edges, injected every turn (~25 tokens).
- **Cabinet** — full event log, queried on demand for specifics.
- **Baked-in** — preferences compiled into tool defaults/ranking.

### Population prior + differential privacy
New users cold-start from crowd patterns (a population prior), with **k-anonymity** suppression + **bounded-mean differential privacy** so no individual leaks. A network effect single-user memories can't have.

### Multi-signal confidence gate
Confidence blends evidence, consistency, taxonomy-match, recency, and outcome (tunable weights) into a 3-tier gate: **act / observe / ask** — with an ask-budget so the LLM or the user is bothered only when genuinely uncertain.

### Multi-timescale memory
A fast lane (recent context) decays quickly; a slow lane (durable identity) persists — handling drift without overwriting who someone durably is.

### Outcome learning (any goal)
`record_outcome(success)` reinforces attributes that led to a good result and weakens ones that backfired. "Success" = purchase, booking, resolved ticket, completed lesson — whatever the site's goal is.

### Communication-style & mood
Deterministically learns terse/verbose, formal/casual, and tracks mood with trend detection — so an agent can match tone and notice rising frustration.

### Injection-resistance
Because writes are arithmetic (not LLM extraction), page/user text can't be "talked into" becoming a belief; injected instructions are sanitized out before they can enter memory.

### Verifiable & unlearnable
Every action is logged in a tamper-evident HMAC chain the user can replay. `forget_everywhere` wipes the profile **and** unlearns the person from the population prior — provable right-to-be-forgotten.

### User-owned supernode
A person signs in across sites; their per-site memories assemble (Lego-style) into one profile **they own**. Cross-site sharing is **default-deny**, sensitive categories walled off.
