# FERNme v0.3.0 — curation, capture adapters, and per-memory meaning

This release is about the two things the r/AI_Agents thread cared about most: the
**editing policy** (what gets kept, replaced, or asked about) and **capturing
memory cheaply from real agents**. Everything is additive and off/transparent by
default, so prior behaviour and benchmarks are unchanged. **Full suite green.**

## 🧠 Curation / editing policy (off by default)

The "librarian" layer FERNme was missing. Deterministic, no LLM:

- **Conflict detection beyond polarity** — catches `likes:x` vs `!likes:x`,
  same-slot value changes (`diet:vegetarian` to `diet:pescatarian`), and declared
  cross-slot semantic clashes (`diet:vegetarian` vs `likes:steak`).
- **Authority axis** — an *inferred* signal can never silently override an
  *explicit* statement. Explicit and recent wins.
- **Supersession, not deletion** — a losing memory is demoted and tombstoned in
  the event log, so the raw record stays honest.
- **It asks instead of guessing** — when an inferred memory contradicts an
  explicit one, `observe()` returns a 0-token clarifying question for the agent to
  raise, rather than flipping the memory silently.

Turn it on with `Config(curation=True)`.

## 🔌 Pluggable capture adapters

How memory gets written, with the token cost printed for each:

| adapter | how tags are made | token cost |
|---|---|---|
| `agent` | the host LLM emits a `FERN_TAGS:` line as a byproduct of its reply | ~20-40/write, no separate call |
| `signal` | structured events (commands, files, git, apps) mapped by rules | 0 tokens |
| `local` | a local model (Ollama/Hermes) or built-in keyword rules | 0 API tokens |

`python -m fernme.capture.install --show` prints the cost table. `AGENTS.md`
documents wiring Claude, Codex, and Hermes.

## 🔍 Per-memory meaning (no more bare tags)

A tag like `topic:salience` used to carry no context. Now every memory can have:

- **context** — the sentence it came from (stored free, no LLM).
- **gloss** — a short "what it means", supplied by the tagger as a byproduct, by a
  local model, or by a deterministic namespace template (0 tokens).

`service.glossary()` returns `{tag: {gloss, context}}`; MCP gains
`remember(glosses=...)` and `recall_glossary`. Cost stays near-zero: context is
free, templates are 0 tokens, agent glosses are a few byproduct tokens. No
separate LLM call anywhere.

## Try it with your agent

See **`AGENTS.md`** for full wiring. Quick version:

```bash
pip install "fernme[api]"                    # now on PyPI
python -m fernme.capture.install --show      # see each method's token cost
```

Then point Claude Code / Codex at the MCP server, or use the `FERN_TAGS:` line
with a local agent (Hermes/Ollama). The engine write stays 0-LLM throughout.

## Honest scope

Numbers are on synthetic and single-persona (Elena) data; a real-human pilot and
a billed Mem0/Honcho head-to-head remain the open experiments. Curation's
cross-slot conflict detection covers a declared mutex table; the rare unlisted
clash escalates rather than guesses. The bounded-working-set for very large
single-user graphs is designed (`docs/v0.3_scaling.md`), not yet built.

**Full changelog:** `CHANGELOG.md` · **Code:** https://github.com/mirkofr/FERNme
