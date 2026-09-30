# FERNme features

Moved from the README so the front page stays short. Status and evidence for each item are in the README's Honest status section.

| | |
|---|---|
| **Zero-LLM deterministic core** | Every write and recall runs with no model calls and bounded cost. Optional opt-in enrichment only proposes connections for human approval, powered by the agent you already use or a model you choose. |
| 📉 **Flat token cost forever** | The prompt card holds **~25 tokens** whether it's a visitor's first day or fifth year. A full-history baseline is **77.4× larger** by 120 interactions. |
| 🧠 **Measured trade-offs, no collapse** | The unified synthetic harness is the README source of truth: FERNme stays zero-call and token-flat across static, abrupt/gradual drift, staleness, context, fragmented-entity, and outcome regimes. It does not win every table, but it is the only method with entity aggregation and an outcome feedback loop. |
| 🧬 **Typed people & relations** | Entities with aliases, contact fields, labeled relations (`ceo_of`, `family_of`, ...), and inert relation facts strengthened Hebbian-style; deterministic path queries; opt-in and byte-identical when off. |
| **Suggest-and-approve canonicalization** | Deterministic alias/entity-link candidates land in a human review queue. Rejections stick, accepted suggestions use existing reversible entity alias APIs, and nothing auto-applies to memory truth. |
| 🪟 **Glass-box & user-owned** | Every preference is visible and editable. People fix what's wrong, delete everything, or export it. Privacy becomes a feature, not a liability. |
| 🏬 **Built for outcomes** | Evaluated by **conversion**, not QA. A simulated storefront shows **+17% conversion lift** vs. non-personalized recommendations. |
| 🧩 **User-owned supernode** | Sign in across sites → your memories assemble like Lego into one profile **you control**, default-deny, sensitive data walled off. Not surveillance — the mirror image of it. |
| **Cost/quality dial** | One engine, a default-off enrichment gate: free key-less `pure` by default, optional agent/model proposal sources when you need typed links and relation candidates, and human approval before truth changes. |
| 🔐 **Verifiable & unlearnable** | Every action is logged in a tamper-evident HMAC chain the user can replay to detect any alteration; `forget_everywhere` wipes the profile **and** unlearns the person from the population prior — provable right-to-be-forgotten. |
| 🛡 **Injection-proof by design** | Writes are arithmetic, not LLM extraction, so page/user text can't be "talked into" becoming a belief — tested that injected instructions never enter memory. |
| 🧠 **Private collective intelligence** | New users benefit from crowd patterns on turn one (cold-start from a population prior), with **k-anonymity + differential privacy** so no individual leaks. A network-effect moat single-user memories can't have. |
| **Cross-user assoc isolation** | Shared co-occurrence edges are k-suppressed by default (`assoc_min_users=2`): a rare pair from one user stays visible to that user, but cannot influence another user's retrieval until at least two users reinforce it. |
| 🗣 **Style & mood memory** | Learns *how* each person communicates (terse/verbose, formal/casual, energy) and tracks their **mood with trend detection**, so the agent can match tone and notice when someone's frustration is rising — in any domain. |
| 🎯 **Outcome-learning, any goal** | Memory is reinforced by *results* — not just recall. `record_outcome(success)` strengthens what worked and weakens what backfired, where "success" is any goal (purchase, booking, resolved ticket, completed lesson…). |
| 🔍 **Explainable** | Ask `why(user, attr)` — get the evidence (observations + good/bad outcomes + dates). No black box. |
| 🔌 **Deployable plumbing** (research preview; harden per SECURITY.md) | SQLite or **Postgres** (tested on real PG 16), REST + **MCP** servers, consent gating, injection-safe writes, proactive triggers — all tested. |

---
