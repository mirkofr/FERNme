# FERNme vs. the closest related work

*An honest comparison. Last updated June 2026.*

This document exists to answer one question directly: **is FERNme a copy of something
that already exists?** Short answer — no, but its *engine mechanism* (Hebbian
co-occurrence + ACT-R-style decay + spreading activation on a graph) is shared, public
cognitive-science machinery used by several recent projects. FERNme's distinct ground is
not the mechanism; it is the **problem it solves** (personalization for many end-users),
the **collective-privacy layer**, and **user-owned cross-surface ownership**. The systems
below are the ones a knowledgeable reader will compare FERNme to.

---

## TL;DR — same toolbox, different machine

Every system here borrows from the same neuroscience toolbox (Hebbian association,
activation decay, spreading activation). What differs is *what the memory is about* and
*who it serves*.

| System | What the memory is *about* | Who it serves | LLM in the loop | Multi-user / collective | Privacy / ownership model | Evaluated on |
|---|---|---|---|---|---|---|
| **FERNme** | each **end-user's** preferences & behavior | **many users**, per site/surface | zero-LLM deterministic core; optional propose-only enrichment | **yes** — population prior + k-anon + DP | consent-gated, cross-surface user-owned supernode, scoped sharing | preference recall, drift, simulated conversion (synthetic) |
| **Ori-Mnemos** | one **agent's** own notes/knowledge | a single agent | heuristic-first; embeddings always; optional LLM | no (single vault) | "your files are portable" (no multi-party sharing) | HotpotQA, LoCoMo (QA) |
| **HeLa-Mem** | one **conversation history** | a single agent/chat | yes (Hebbian Distillation + embeddings) | no | none stated | LoCoMo (conversational QA) |
| **HippoRAG / HippoRAG 2** | a **document corpus** | a retrieval pipeline | yes (OpenIE indexing + embeddings) | no | none stated | HotpotQA, MuSiQue, 2Wiki, PopQA, NarrativeQA |
| Mem0 / Zep / Letta | conversation history / facts | a single agent/user | yes (extraction) | no | hosted/cloud | LongMemEval, LoCoMo |

The takeaway: FERNme is the only one whose memory is **about end-users, for an agent that
acts on their behalf, across many tenants, with a privacy-preserving collective layer**.
The others are **single-corpus retrieval / single-agent memory** systems.

---

## 1. Ori-Mnemos — the closest *vocabulary* match

**What it is.** Local-first persistent memory for *one AI agent* — its identity, notes,
and operational state as markdown files, with `[[wiki-links]]` as graph edges. Built on
the "Recursive Memory Harness" idea: retrieval follows the graph, recurses on hard
queries, and reshapes the graph as it's used. v0.5.0, ~579 tests, npm package, 16 MCP
tools, adapters for Claude Code / Cursor / Codex / Hermes. Apache-2.0.

**What it shares with FERNme.** The exact engine vocabulary: ACT-R decay, spreading
activation, Hebbian co-occurrence, plus a flat token-cost story. On paper the two
"engine" descriptions read almost identically.

**How FERNme differs.**
- Ori's Hebbian edges grow between **notes that were retrieved together**. FERNme's grow
  between **attributes a user exhibits together** (behavioral co-occurrence, not retrieval
  co-occurrence).
- Ori is **single-vault / single-agent**. FERNme is **multi-tenant** (site × user) and adds
  a **population prior** so a brand-new user starts warm — a layer Ori has nothing like.
- Ori's "sovereignty" means *your files are portable*. FERNme's ownership is a
  **multi-party** model: a user signs in across sites, their memory assembles into a
  supernode they own, with default-deny scoped sharing and sensitive-category walls.
- Ori retrieves with a 4-signal fusion that **always uses embeddings** (MiniLM). FERNme's
  `pure` mode uses **no embedding model at all** — pure graph arithmetic.

**Where FERNme is better (in its niche).** It serves *thousands of distinct end-users*
privately from one deployment with a collective cold-start, and carries a real
privacy/ownership story (consent, DP, scoped cross-site sharing, right-to-be-forgotten
that also unlearns from the prior). Ori isn't built for any of that.

**Where FERNme is weaker.** Ori is far more mature: v0.5 vs v0.1, ~579 tests vs 83, an
installable npm package, agent adapters, and **head-to-head benchmarks on standard
datasets** (HotpotQA, LoCoMo) against Mem0. Its retrieval (RL Q-values, bandit stage
selection, recursive decomposition) is more sophisticated than FERNme's plain spreading
activation. For document/QA recall, Ori would likely win.

---

## 2. HeLa-Mem — Hebbian memory for *conversations*

**What it is.** An academic (HKUST-GZ et al., arXiv 2026) bio-inspired memory for LLM
agents that models **conversation history** as a dynamic Hebbian graph. Two levels: an
episodic graph that strengthens through co-activation, and a semantic store built by
"Hebbian Distillation" — a Reflective Agent finds dense hub clusters and uses an **LLM to
distill** them into reusable semantic knowledge. Dual-path retrieval (episodic +
semantic) via spreading activation, plus adaptive forgetting (prune by low weight + age +
inactivity). Evaluated on LoCoMo; beats A-Mem, Mem0, MemoryOS with fewer context tokens.

**What it shares with FERNme.** Hebbian graph, edge decay, spreading activation, hub
detection, threshold-based forgetting — and a token-efficiency argument. The mechanism
family is the same.

**How FERNme differs.**
- HeLa-Mem remembers a **single user's conversation**; its co-activation is over **dialogue
  turns**. FERNme remembers **many users' preferences/behavior** across surfaces.
- HeLa-Mem's consolidation **requires an LLM** (Hebbian Distillation) and embeddings for
  base activation. FERNme's deterministic write/recall core is model-free; optional enrichment only proposes suggestions for human approval.
- No multi-tenant layer, no population prior, no privacy/ownership/consent model, no
  outcome learning. FERNme has all four.
- HeLa-Mem is evaluated on **conversational QA**; FERNme on **preference recall, drift, and
  simulated conversion**.

**Where FERNme is better (in its niche).** Multi-user personalization with a private
collective prior and user-owned cross-surface memory — none of which HeLa-Mem attempts.
Cheaper floor (no mandatory LLM/embeddings).

**Where FERNme is weaker.** HeLa-Mem is a **published, benchmarked** result on an accepted
dataset (LoCoMo) with ablations across four LLM backbones. FERNme has no peer-reviewed
benchmark yet. For long-conversation recall, HeLa-Mem's LLM-distilled semantic layer
likely captures nuance FERNme's arithmetic card does not.

---

## 3. HippoRAG / HippoRAG 2 — the academic root of the retrieval idea

**What it is.** A neurobiologically-inspired **RAG / memory framework** (OSU-NLP,
NeurIPS'24 and ICML'25) for retrieving over a **document corpus**. It builds a knowledge
graph by LLM **OpenIE** (entity/relation extraction), then runs **Personalized PageRank**
(the formal version of spreading activation) to do multi-hop retrieval — finding passages
linked through chains of entities even with no lexical overlap. Strong on HotpotQA,
MuSiQue, 2Wiki, PopQA, NarrativeQA.

**What it shares with FERNme.** Spreading activation over a graph as the retrieval
principle. FERNme's "follow the edges to related preferences" is the same idea HippoRAG
formalized as Personalized PageRank.

**How FERNme differs.**
- HippoRAG is a **document-retrieval engine** — no users, no preferences, no personalization,
  no privacy, no outcomes. It answers "which passages are relevant to this query?"
- It is **heavy**: LLM-based OpenIE for indexing, large embedding models (NV-Embed), GPUs /
  vLLM / OpenAI keys. FERNme's deterministic core runs on a laptop with no model calls and no embeddings; optional enrichment is separate and propose-only.
- HippoRAG is stateless about *who* is asking; FERNme's entire point is *whom* it's for.

**Where FERNme is better (in its niche).** It's a personalization/ownership product, not a
retrieval library — different category. Far cheaper and lighter; runs with zero
infrastructure.

**Where FERNme is weaker.** HippoRAG is **state-of-the-art, peer-reviewed multi-hop
retrieval** with public datasets and code. If the task is "retrieve the right facts from a
big corpus," HippoRAG is in a different league. FERNme doesn't do corpus retrieval at all.

---

## 4. The incumbents it positions against (context)

- **Mem0** — vector store + LLM extraction/update on each turn; widely adopted; cloud
  (Redis + Qdrant). Architecturally *opposite* to FERNme (LLM-on-write vs zero-LLM deterministic core with optional propose-only enrichment).
- **Zep / Graphiti** — temporal knowledge graph with validity windows; strong on
  long-memory benchmarks; Postgres/cloud.
- **Letta / MemGPT** — OS-inspired tiered memory (core/recall/archival); an agent runtime,
  not a memory layer.

None are multi-tenant personalization layers, and none carry a collective-privacy or
user-ownership model. FERNme isn't competing on their axis (single-agent long-term chat
memory); it's a different product.

---

## Bottom line

- The **engine mechanism is not novel** — Ori-Mnemos, HeLa-Mem, and HippoRAG all use the
  same Hebbian/decay/spreading-activation family, and several are more mature and actually
  benchmarked. FERNme should **cite them, not imply it invented the mechanism.**
- FERNme's **defensible, genuinely-uncommon ground** is the *system*, not the engine:
  1. **Multi-tenant personalization** — memory *about end-users*, for an agent acting on
     their behalf, many users per deployment.
  2. **Private collective intelligence** — population prior + k-anonymity + differential
     privacy so newcomers start warm without anyone leaking.
  3. **User-owned cross-surface supernode** — assembled by sign-in, consent-gated,
     default-deny scoped sharing, sensitive categories walled off.
  4. **Outcome orientation** — reinforced by results (conversion/booking/resolution), not QA.
- **Honest weaknesses to own publicly:** early maturity (v0.1, 83 tests), **no standard
  benchmark** yet (synthetic/LLM-authored only), and a simpler, less-proven retrieval path.
  The single highest-leverage next step is a real benchmark (LoCoMo-style for memory, or a
  live personalization pilot) so the claims stop being synthetic.

**Recommended framing for the README/paper:** lead with *"a user-owned personalization
memory layer for agents that serve many people, with a privacy-preserving collective
prior"* — and explicitly acknowledge the Hebbian-memory lineage (Ori-Mnemos, HeLa-Mem,
HippoRAG) rather than presenting the engine as new.

---

## Sources

- Ori-Mnemos — https://github.com/aayoawoyemi/Ori-Mnemos
- HeLa-Mem (arXiv 2026) — https://arxiv.org/html/2604.16839v1 · code: https://github.com/ReinerBRO/HeLa-Mem
- HippoRAG (NeurIPS'24) — https://arxiv.org/abs/2405.14831 · HippoRAG 2 (ICML'25) — https://arxiv.org/abs/2502.14802 · code: https://github.com/OSU-NLP-Group/HippoRAG
- Mem0 — https://github.com/mem0ai/mem0 · Mem0 paper — https://arxiv.org/abs/2504.19413
- Memory-framework overviews (2026) — https://baeseokjae.github.io/posts/best-ai-agent-memory-frameworks-2026/ · https://mem0.ai/blog/state-of-ai-agent-memory-2026
- Puda: Private User Dataset Agent — https://arxiv.org/pdf/2602.08268
