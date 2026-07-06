# FERNme v0.2.0 — salience, categories, and a memory map you can click

This release deepens FERNme's "see and own your memory" story and hardens the engine,
while keeping the core promise intact: **zero-model-call deterministic writes, flat token cost, user-owned.**
Everything new is additive and off/transparent by default — all prior behaviour and
benchmarks are unchanged. **91 tests passing.**

## Highlights

### 🧠 Salience-modulated forgetting
Memories that are *behaviorally significant* now resist forgetting. Each edge can carry a
`salience ∈ [0,1]` that slows its decay (`λ_eff = λ·(1 − β·salience)`), fed by signals
FERNme already sees — strong outcomes, dislikes, rating extremity — **no LLM**. It's
decoupled from confidence (**retain vs. act**): a single intense signal is remembered, but
still verified before it's acted on. Off by default (`salience_beta = 0`), so it changes
none of the existing numbers until a deployment opts in.

### 🗂 Deterministic memory categories
A new `fernme/categories.py` rolls FERNme's fine-grained namespaces (`pref:`, `rel:`,
`goal:`, …) into a small, stable set of categories (values, people, facts, habits, media,
emotional) — a **pure lookup table, no LLM, identical for everyone**. `graph()` now emits a
`category` per node and the category list, so any client groups memory the same way.

### 🔍 `/why` over HTTP
The existing explainability evidence (what's behind a stored memory) is now exposed as a
**`/why` REST endpoint**, so any UI can show *why* a memory exists.

### 🫧 Interactive memory map (demo)
`demo/elena/memory_map.html`: Elena at the center, category **bubbles** with physics,
**association lines** between related memories, and **click-to-inspect** any memory
(strength, confidence, known/tentative, connected memories). A tangible glass-box view.

### 🛠 Fix: database forward-compatibility
Databases created **before** the `fast`/`salience` columns existed previously failed on
write (`CREATE TABLE IF NOT EXISTS` never alters an existing table). Both the SQLite and
Postgres stores now **auto-migrate** missing columns on open. Existing data just works.

## Also in this release
- The **Elena natural-data evaluation** + a LoCoMo-style QA head-to-head (FERNme vs.
  zero-model-call baselines), the **paper** (Markdown + LaTeX), and a **related-work comparison**.

## Honest scope (unchanged)
Numbers are on synthetic or single-person data; a real-human pilot and a billed Mem0 (LLM)
head-to-head remain the open experiments. This is a **research preview** — harden per
`SECURITY.md` before production.

## Upgrade notes
- Drop-in. No config changes required; old DBs migrate automatically.
- To enable salience, set `salience_beta > 0` in `Config`.

**Full changelog:** see `CHANGELOG.md` · **Code:** https://github.com/mirkofr/FERNme
