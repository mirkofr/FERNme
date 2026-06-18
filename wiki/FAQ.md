# FAQ

**Is FERNme really zero-LLM?**
The hot read/write path is, in every mode. `gated`/`offline` modes use a small LLM occasionally (novel free text or nightly batch) — never per turn. `svc.llm_calls` counts every call.

**Does adding an LLM blow up the cost?**
No. It's write-side only, occasional, and a cheap model — it never touches the flat per-turn read. Structured input needs no LLM at all. See [[Memory Modes]].

**How is this different from Mem0 / Zep / Letta?**
Different category. Those are conversational memories written by an LLM and benchmarked on QA. FERNme is a per-user *preference* graph, written without an LLM, evaluated by *actions*, multi-tenant and user-owned. It leads on write cost, interpretability, and per-site ownership; it's honestly behind on nuanced/causal preferences and ecosystem.

**Is my data private?**
Consent-gated; glass-box (see/edit/export/delete); cross-site sharing is opt-in and default-deny; collective priors use k-anonymity + differential privacy; deletion is provable and cascades into the prior.

**Is it production-ready?**
It's a research preview. Plumbing is tested (SQLite/Postgres, REST/MCP, consent, injection-safe writes), but turn on `FERNME_API_KEY` + TLS, encrypt the DB, add rate limiting, and review regulated data before real deployment. See `SECURITY.md`.

**Why the name FERNme?**
**F**uzzy-**E**dged **R**ecall **N**etwork — and a fern grows recursively, which is the long-term organization idea. "me" = your memory, owned by you.

**Can I cite it?**
Yes — see `CITATION.cff` and the manuscript in `PAPER.md`.
