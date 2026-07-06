# Using FERNme with an agent (Claude, Codex, Hermes, ...)

FERNme gives an agent persistent, user-owned memory. The agent never manages a
database. It just **recalls** a small card at the start of a turn and **remembers**
a few tags at the end. The deterministic write/recall core makes no model calls,
so the default token cost is the handful of tag tokens the agent already emits.
Optional enrichment uses explicit proposal tools and still waits for human
approval before truth changes.

There are two ways to connect, depending on what your agent supports.

## Option A — MCP (Claude Code, Codex, any MCP-capable agent)

FERNme ships an MCP server exposing these tools:

| tool | what it does |
|------|--------------|
| `grant_consent(site, user)` | one-time: allow remembering this user |
| `recall_card(site, user, context)` | the token-minimal memory card to inject into the prompt |
| `remember(site, user, tags, text, source)` | store tags (and optional text); `source` is `stated` or `inferred` |
| `recall_events(site, user, contains)` | search the raw history (the Cabinet) |
| `edit_memory(site, user, attr, weight)` | glass-box override of one memory |
| `forget_me(site, user)` | delete everything (right to be forgotten) |
| `propose_relation(site, user, subject_id, relation, object_id, note)` | enqueue a typed relation suggestion for human review |
| `propose_entity_link(site, user, alias_attr, entity_id)` | enqueue an entity alias/link suggestion for human review |

Install and run it:

```bash
pip install "fernme[api]" mcp
python -m fernme.api.mcp_server
```

Point your agent at it. Example MCP config (Claude Code / Codex `mcp` block):

```json
{
  "mcpServers": {
    "fernme": { "command": "python", "args": ["-m", "fernme.api.mcp_server"] }
  }
}
```

The agent's loop becomes:

1. **Start of turn:** call `recall_card` and put the result in context.
2. **End of turn:** call `remember` with a few tags. Mark `source="stated"` when
   the user said it outright, `source="inferred"` when you guessed it.
3. **If `remember` returns `questions`:** a new memory conflicts with something the
   user told you before. Ask the question; don't overwrite silently.

## Option B — no MCP (Hermes / Ollama / any local agent)

Use the capture CLI plus a one-line tag convention. Have the agent end its reply
with a `FERN_TAGS:` line as a byproduct of the answer it's already writing:

```
...your normal reply...
FERN_TAGS: pref:concise topic:python !likes:meetings
```

A few lines then persist it. FERNme makes 0 extra model calls in the engine write. The
`agent` adapter parses the `FERN_TAGS:` line straight out of the reply text:

```python
from fernme.service import FernService
from fernme.store.sqlite_store import SQLiteStore
from fernme.capture import load_pipeline

svc = FernService(store=SQLiteStore("memory.db"))
svc.store.set_consent("demo.com", "elena", True)
pipe = load_pipeline(svc, "demo.com", "elena", "fern.toml")
pipe.ingest({"kind": "chat", "text": reply_text})   # reply_text includes the FERN_TAGS: line
```

For truly token-free capture from behavior (commands, files, git), see the
`signal` adapter in `fernme/capture/` — it maps structured events to tags with no
model at all. Pick adapters with:

```bash
python -m fernme.capture.install --show          # see the cost of each method
python -m fernme.capture.install --methods agent,signal
```

## The authority rule (why `source` matters)

`stated` outranks `inferred`. An inferred guess can never silently overwrite
something the user stated explicitly. If they conflict (e.g. the user said
`diet:vegetarian` two sessions ago and now behavior suggests `likes:steak`),
FERNme returns a `questions` entry instead of flipping the memory, so the agent
asks the user. Turn this on with `Config(curation=True)`; it's off by default.

## Quick test (60 seconds)

```python
from fernme.service import FernService
import dataclasses
from fernme.config import DEFAULT

svc = FernService(cfg=dataclasses.replace(DEFAULT, curation=True))
svc.consent("demo.com", "elena", True)
svc.observe("demo.com", "elena", "chat", {"tags": ["diet:vegetarian"], "source": "stated"})
out = svc.observe("demo.com", "elena", "chat",
                  {"tags": ["likes:steak"], "source": "inferred"})
print(out["questions"])   # -> a clarifying question, not a silent overwrite
print(svc.card("demo.com", "elena"))   # the memory card an agent would inject
```

That's the whole contract: recall a card, remember some tags, answer the
questions it hands back. The memory stays cheap, inspectable, and owned by the user.
