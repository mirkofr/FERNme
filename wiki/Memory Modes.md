# Memory Modes

One engine, a deployment-level dial: `FernService(memory_mode=...)`. Every hot write and recall stays model-free in every mode. Optional enrichment is a separate proposal tier.

| path | model use | cost accounting | status |
|---|---|---|---|
| `pure` (default) | none | cheapest, flat | tested, key-less |
| agent proposals | external agent proposes through MCP tools | `svc.llm_calls` remains 0 | wired, human-approved |
| batch `enrich(llm_fn=...)` | caller-supplied model function, off hot path | `svc.llm_calls` counts batch calls and reports token estimate | mock-validated synthetic eval |
| no source configured | none | clean no-op | tested graceful skip |

## How it works

- `propose_relation(...)` and `propose_entity_link(...)` enqueue suggestions into the existing human review queue.
- Accepting applies through existing reversible service paths; rejecting sticks.
- Model or agent output is untrusted data and must pass the same validation.
- The old `gated`/`offline` mode names remain for compatibility, but they do not write model-derived truth during `observe`.

## Configure

```python
from dataclasses import replace
from fernme.config import DEFAULT
from fernme.service import FernService

svc = FernService(cfg=replace(DEFAULT, enrichment_enabled=True))
```

See [[Benchmarks]] for the synthetic mock enrichment eval.