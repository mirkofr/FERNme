# FERNme v0.1.0 — first public release

Per-site, user-owned Hebbian preference-graph memory for transactional agents.
Cheap to write, flat to read, interpretable, and owned by the people it remembers.

## Highlights
- **Historical release framing:** deterministic Hebbian writes, spreading-activation retrieval,
  token-minimal memory card (~25 tokens, flat as the profile grows; ~77× smaller than
  full-history-in-context by 120 interactions).
- **Cost/quality dial** (`memory_mode`: pure / gated / offline) — LLM is an exception,
  not the default; gated/offline reach most of LLM-grade quality at a fraction of the cost.
- **Ingestion bridge**: per-site catalog + **controlled namespaced vocabulary** so a
  concept never drifts across time.
- **Learns from outcomes** (any goal), **communication-style & mood** memory, **explainable**
  provenance (`why`), **multi-signal confidence** + ask-budget gate, **self-tuning forgetting**,
  **multi-timescale** (fast context vs. slow identity).
- **User-owned & private**: consent-gated, glass-box editable, k-anonymity + differential-privacy
  collective priors, tamper-evident audit chain, provable right-to-be-forgotten.
- **Deployable**: SQLite or Postgres (tested vs. real PG 16), REST + MCP servers, glass-box web UI.

## Benchmarks (synthetic / LLM-authored — real-human pilot pending)
- Agentic recall on LLM-authored profiles: 75% preference coverage, 100% formality,
  94%/100% mood, 100% injection-ignored, 7.3× note→card compression.
- Drift: 0.72 vs. 0.13 for a frequency counter; context-conditioned: 0.62 vs. 0.51.
- 77 tests passing.

## Honest status
Research preview. All numbers are on synthetic or LLM-authored data; the Mem0 head-to-head
needs an API key and is not yet run; recursive/supernode organization is roadmap, not built.

## License
Apache-2.0 © 2026 Acquilab Inc. · https://fernme.dev
