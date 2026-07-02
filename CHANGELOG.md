# Changelog

All notable changes to FERNme. Pre-1.0: anything may change (semver 0.y.z).

## [0.4.0-unreleased] — entity layer groundwork

### Added
- Persisted edge provenance (`stated`/`inferred`) in SQLite and Postgres stores,
  including migration defaults and consolidation snapshot/undo preservation.
- Added deterministic structured-field extraction at capture ingest for email,
  phone, URL, handle, and ISO-date payload retention.

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

- **Near-zero-LLM core** — saturating Hebbian writes (no LLM), spreading-activation
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
