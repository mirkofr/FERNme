# Changelog

All notable changes to FERNme. Pre-1.0: anything may change (semver 0.y.z).

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
