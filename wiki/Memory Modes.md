# Memory Modes

One engine, a deployment-level dial: `FernService(memory_mode=...)`. The hot write path stays LLM-free in every mode; modes differ only in *when* an LLM is invoked.

| mode | LLM use | cost | status |
|---|---|---|---|
| `pure` (default) | none | cheapest, flat | ✅ tested, key-less |
| `gated` | one small call **only on novel free-text** | ~tiny, occasional | 🧪 experimental — needs a model |
| `offline` | batched `consolidate()` enrichment, off the hot path | ~tiny, amortized | 🧪 experimental — needs a model |

## How it works
- A pluggable **tagger** (`tagging.py`) does any LLM work; you pass `llm_fn`, optionally constrained to a controlled **vocabulary** for cross-model consistency.
- `gated` calls the LLM only when the deterministic mapping finds nothing and there's free text to interpret.
- `offline` runs enrichment as a batch job (nightly), so there's ~zero marginal per-interaction cost.
- `svc.llm_calls` counts every LLM invocation for cost transparency.

## Configure
```python
from fernme.service import FernService
from fernme.tagging import LLMTagger

# pure (default) — no LLM, no key
svc = FernService(memory_mode="pure")

# gated — LLM only on novel free text
tagger = LLMTagger(my_llm_fn, vocabulary=my_vocab)   # my_llm_fn(prompt)->str
svc = FernService(memory_mode="gated", tagger=tagger)
```

> The gated/offline **quality** is modeled until run against a real model; the wiring is tested with a mock LLM. See [[Benchmarks]] for the cost/quality Pareto.
