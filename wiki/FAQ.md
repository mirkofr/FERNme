# FAQ

**Is FERNme really zero-LLM?**
The deterministic write/recall core is zero-LLM in every mode. Optional enrichment is default-off, off the hot path, and propose-only.

**Does adding enrichment write memories automatically?**
No. Agent/model output is untrusted data. It can only enqueue suggestions for human accept/reject. Accepted suggestions apply through existing service APIs.

**Does adding a model blow up cost?**
No model is required. Agent-driven proposals spend the caller agent's tokens and leave `svc.llm_calls` at 0. Batch `enrich(llm_fn=...)` counts only FERNme-initiated model calls and reports a token estimate.

**How is this different from Mem0 / Zep / Letta?**
Different category. Those are conversational memories commonly written by an LLM and benchmarked on QA. FERNme is a per-user preference graph, written by a deterministic core, evaluated by actions, multi-tenant and user-owned.

**Is my data private?**
Consent-gated; glass-box; exportable and deletable; cross-site sharing is opt-in and default-deny; collective priors use k-anonymity + differential privacy.