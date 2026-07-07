# Changelog

All notable changes to FERNme. Pre-1.0: anything may change (semver 0.y.z).

## [0.4.0-unreleased] — entity layer groundwork

### Added
- Persisted edge provenance (`stated`/`inferred`) in SQLite and Postgres stores,
  including migration defaults and consolidation snapshot/undo preservation.
- Added deterministic structured-field extraction at capture ingest for email,
  phone, URL, handle, and ISO-date payload retention.
- Added the typed entity layer: additive SQLite/Postgres tables and deterministic
  service APIs for entities, aliases, fields, and Hebbian typed relations.
- Rejected reversed relation surfaces such as `buys_from` instead of storing
  direction-inverted canonical relations.
- Added opt-in entity-aware retrieval integration: alias activation aggregation,
  compact card enrichment, card token estimates, and one-hop stated relation pull.
- Added entity-aware graph/map rendering: canonical entity nodes with alias
  grouping, labeled typed-relation edges, and a synthetic Elena entity map demo.
- Added fictional entity-layer acceptance fixtures covering commerce and
  non-commerce research/family scenarios.
- Added `python -m fernme.eval.entities`, a reproducible synthetic micro-eval for
  the A2 alias-fragmentation dilution effect with entity aggregation off vs. on.
- Added `python -m fernme.eval.harness`, a synthetic hidden-answer-key eval gate
  covering static, abrupt drift, gradual drift, staleness, contextual,
  fragmented-entity, and outcome regimes across FERNme, entity flags, recency,
  frequency, and pure-Python BM25 Cabinet baselines.
- Reconciled README benchmark claims to the unified harness as the public source
  of truth, including the measured trade-offs, flat token cost, zero-model-call deterministic core,
  entity aggregation, and FERNme-only outcome feedback loop.
- Added relation facts for typed entity relations in SQLite/Postgres, with
  deduplicated inert notes, explicit fact deletion, and entity-forget cascade.
- Added memory map v2 entity-kind rendering for the Elena demo: owner/person/org/
  project colors, pink info markers, typed relation edges with relation-fact
  badges, and edge inspection with most-recent facts first.
- Added suggest-and-approve canonicalization: deterministic alias-merge and
  entity-link suggestions, persistent per-user review queues in SQLite/Postgres,
  REST/MCP adapters, and the synthetic `python -m fernme.eval.canonicalization`
  precision/recall report. Nothing auto-applies to memory truth.
- Added default-on cross-user assoc k-suppression (`assoc_min_users=2`) so rare
  one-user co-occurrence edges stay self-visible but do not influence other users'
  retrieval on shared sites until enough distinct users reinforce them.
- Added default-off propose-only enrichment: agent/MCP relation and entity-link
  proposals plus optional caller-supplied batch `enrich(llm_fn=...)` enqueue
  suggestions for human approval; deterministic write/recall stays zero-model-call.
- Documented first real-profile validation (n=1, maintainer's own 722-tag profile):
  entity flags improved a fragmented person's card rank 11→6, surfaced a
  previously missed `contact_of` relationship, and kept token cost flat.
- Added MCP packaging: `fernme-mcp` console script, bundled Codex and Claude
  Code/Cowork plugin manifests, a standing memory skill, docs, and stdio smoke
  coverage using a temporary synthetic SQLite database.
- Made the Claude/Cowork plugin GitHub-marketplace installable without PyPI by
  adding a repo-root marketplace and switching shipped MCP configs to `uvx`
  from the Git repo with the `mcp` extra.
- Pinned shipped plugin MCP configs to the reproducible test release
  `0.4.0-beta.1` and aligned the package/plugin versions for external testers.
- Added deterministic Obsidian vault import via service, CLI, and MCP: note text
  is stored as Cabinet data, frontmatter tags use the existing vocabulary, and
  wikilinks/aliases queue human-reviewed suggestions only.
- Made installs self-configuring for `0.4.0b1`: the default package includes MCP,
  all entry points share `~/.fernme/fernme.db` unless `FERNME_DB` overrides it,
  `fernme-mcp --print-db-path` exposes the path, and plugin configs pin
  `v0.4.0b1`.

## [0.3.0] — curation, capture adapters, and per-memory meaning

### Added
- **Curation / editing policy** (`fernme/curation.py`, off by default) — deterministic
  conflict detection (polarity, same-slot value change, declared semantic mutex),
  an authority axis (an *inferred* signal never silently overrides an *explicit*
  statement), supersession recorded as a tombstone event, and a 0-token clarifying
  question surfaced from `observe()` instead of a silent overwrite.
- **Pluggable capture adapters** (`fernme/capture/`) — `agent` (host LLM emits tags
  as a byproduct, ~20-40 tok), `signal` (structured events to tags, 0 tokens), and
  `local` (rules now, Ollama/Hermes later, 0 API tokens). Installer prints the
  per-method token cost; `AGENTS.md` documents wiring Claude/Codex/Hermes.
- **Per-memory meaning** (`fernme/glossary.py`) — `context` (the sentence a memory
  came from, stored free) and `gloss` (supplied by the tagger or a deterministic
  namespace template, 0 tokens). `service.glossary()` assembles `{tag: {gloss,
  context}}`; MCP gains `remember(glosses=...)` and `recall_glossary`.

### Notes
- All additive and off/transparent by default; prior behaviour and benchmarks
  unchanged. 119 tests passing.

## [0.2.1] — recall latency fix

### Fixed
- **Recall is no longer O(all association edges).** `AssocGraph.neighbors()` scanned
  every association edge on every node, every hop — O(nodes × edges × hops) — pushing
  recall past 200ms at a few hundred memories. Added an adjacency index (`_adj`, built
  lazily and kept in sync by `set_edge()`), making `neighbors()` O(degree). Measured
  p95 dropped from ~222ms to ~2ms at 200 memories, and stays ~30ms at 1,000 memories
  over a 50k-edge graph. No API or behavior change; pure performance.

### Added
- `tests/test_perf_recall.py` — index-correctness + a latency-ceiling regression guard.
- `docs/v0.3_scaling.md` — the measurements and the bounded-working-set plan for the
  remaining single-large-graph case.

## [0.2.0] — salience, categories, memory map

### Added
- **Salience-modulated forgetting** — optional per-edge `salience` (off by default,
  `salience_beta=0`) so behaviorally significant memories (strong outcomes, dislikes,
  rating extremity) decay slower. Decoupled from confidence: retain vs. act.
- **Deterministic memory categories** (`fernme/categories.py`) — a reproducible,
  no-LLM `namespace -> category` rollup; `graph()` now emits a `category` per node and
  the category list.
- **`/why` REST endpoint** — exposes the existing explainability evidence over HTTP.
- **Interactive memory-map demo** (`demo/elena/`) — category bubbles, associations,
  Elena at the center, click-to-inspect a memory.
- Natural-data **Elena evaluation** + LoCoMo-style QA, paper (Markdown + LaTeX),
  related-work comparison.

### Fixed
- **DB forward-compatibility:** auto-migrate `user_edges` to add `fast`/`salience`
  columns on open (previously, DBs created before these columns failed on write).

### Notes
- Salience and categories are additive and off/transparent by default; existing
  behaviour and all prior numbers are unchanged.

## [0.1.0] — first public release
Initial open-source release. A per-site, user-owned Hebbian preference-graph memory
for transactional agents. Highlights:

- **Historical core framing** — saturating Hebbian writes, spreading-activation
  retrieval, ACT-R decay, token-minimal flat memory card.
- **Ingestion bridge** — per-site catalog + controlled namespaced vocabulary (no tag drift).
- **Cost/quality dial** — `memory_mode` pure / gated / offline.
- **Outcome learning** (any goal), **communication-style & mood** memory, **explainable
  provenance** (`why`), **multi-signal confidence** + ask-budget gate, **self-tuning
  forgetting**, **multi-timescale** memory.
- **User-owned & private** — consent-gated, glass-box editable, k-anonymity + differential-
  privacy collective priors, tamper-evident audit chain, provable right-to-be-forgotten,
  user-owned cross-site supernode.
- **Deployable** — SQLite or Postgres (tested vs. real PG 16), REST + MCP servers, glass-box UI.
- 77 tests passing. Apache-2.0.

> Research preview: results are on synthetic / LLM-authored data; a real-human pilot and the
> Mem0 head-to-head are the pending next steps. (Built through several internal iterations
> before this first public cut.)
