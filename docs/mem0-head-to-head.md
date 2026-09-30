# FERNme vs Mem0 head-to-head (owner-run)

`fernme/eval/mem0_h2h.py` runs real Mem0 OSS against FERNme on the same synthetic
harness scenarios (`static`, `abrupt_drift`, `gradual_drift`, `staleness`,
`contextual`) with the same hidden answer keys and metrics as
`fernme.eval.harness`. Nothing here runs against a paid API in CI.

## Run it

```bash
pip install -e ".[dev]" mem0ai
python -m fernme.eval.mem0_h2h --check              # offline preflight: installed? key? call volume
export OPENAI_API_KEY=...                            # or pass --mem0-config mem0.json
python -m fernme.eval.mem0_h2h --backend mem0 --seeds 3 --json reports/mem0_h2h.json
```

`--seeds 3` makes about 813 Mem0 `add()` calls (the preflight prints the exact
number). Defaults: `gpt-4.1-mini` at temperature 0 and `text-embedding-3-small`;
override with `--llm-model`, `--embedder-model`, or a full `--mem0-config` JSON.
Each scenario uses a fresh temporary Qdrant collection and history DB, and
`MEM0_TELEMETRY` is set to `False` for the run.

`--backend stub` swaps Mem0 for a keyword-overlap stub so the plumbing and
scoring can be tested without any API call. Stub numbers are not Mem0 numbers
and must not be quoted as such.

## Fairness contract

- Same events, same order. FERNme receives each event's tags natively; Mem0
  receives the same tags rendered as a plain-English sentence plus the event text.
- Mem0 returns prose memories. They are mapped back to attributes lexically: an
  attribute counts when its value phrase (`jasmine tea`) appears in a returned
  memory and no negation cue precedes it in the same clause. This mapper can
  under- or over-credit Mem0; report results with that caveat.
- `llm_calls` for Mem0 counts LLM calls during `add()` across the scenario.
  FERNme and the heuristic baselines make none.
- `fragmented_entity` and `outcome` are excluded: they test FERNme-only
  mechanisms with no Mem0 analogue.
- Scenarios are synthetic. Results describe these fixtures, not real users.

## What is known before a real run

With the real Mem0 2.2.1 pipeline driven by a fake in-process model (no API),
each `add()` made exactly **one** LLM extraction call plus embedding calls
(30 LLM calls for 30 events). Older FERNme docs assumed about two calls per
write; one per `add()` is the measured figure for this Mem0 version.
Quality numbers need the owner-run step above.
