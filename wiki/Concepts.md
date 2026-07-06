# Concepts

### Fuzzy 0-9 edges
Each user is a sparse node connected to attributes by edges weighted 0-9, stored sparsely as deviations from a population prior.

### Hebbian write (zero-model-call core)
On each event, co-active attributes strengthen via a saturating update: pure arithmetic, no model call.

### Propose-only enrichment
When `enrichment_enabled=True`, an external agent or caller-supplied `llm_fn` may propose typed relations and entity links. FERNme validates the proposal as untrusted data, enqueues it for human review, and does not write memory truth until accepted.

### Typed entities and aliases
Entities are opt-in records for people, organizations, projects, places, things, and other named objects. Aliases connect existing tag attributes to one entity without rewriting the original tag graph.

### Typed relations and facts
Relations connect entities with controlled labels such as `friend_of`, `family_of`, `works_at`, `ceo_of`, or `works_on`. Relation strength is Hebbian; relation facts are inert display notes.

### Spreading activation
Retrieval activates the user node plus current context and lets activation flow over weighted edges. The brightest nodes are relevant now without per-turn vector search.

### Memory card (three tiers)
- **Card** - top activated edges, injected every turn.
- **Cabinet** - full event log, queried on demand for specifics.
- **Baked-in** - preferences compiled into tool defaults/ranking.

### Population prior + differential privacy
New users cold-start from crowd patterns, with k-anonymity suppression and bounded-mean differential privacy so no individual leaks.

### Outcome learning
`record_outcome(success)` reinforces attributes that led to a good result and weakens ones that backfired.

### Injection-resistance
Stored text and proposal text are data, never instructions. Injected instructions are sanitized or dropped before they can enter memory truth.