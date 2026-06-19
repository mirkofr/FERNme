# FERNme demo — Elena (natural single-user memory)

Builds FERNme memory from 86 free-form diary entries about one fictional person
("Elena natural memory" dataset) and evaluates the engine's behavior. This is the
material behind Section 6 of the paper.

## What's here
- `eval_elena.py` — ingest all 86 entries, produce the mechanics plots (cost, growth,
  drift, confidence, weight distribution, top hubs, cost bars) + a salience probe.
- `eval_elena_qa.py` — LoCoMo-style QA: FERNme vs frequency/recency at matched budget,
  plus an accuracy-vs-budget sweep.
- `elena_memory_graph.html` — interactive graph of Elena's whole memory (open in a browser).
- `Elena_FERNme_memory.md` — human-readable readout of what FERNme remembered.
- `figures/` — generated plots (01–12) + summary JSON.

## Run it
The dataset is **not** bundled (it's external and not ours to redistribute). Point the
scripts at your copy of the `Elena memory` folder:

```bash
DIR="/path/to/Elena memory" python demo/elena/eval_elena.py
DIR="/path/to/Elena memory" python demo/elena/eval_elena_qa.py
python demo/salience_demo.py          # salience figure (no dataset needed)
```

## Honest scope
The tag extraction is done by the agent/parser, so fact coverage is high by construction.
This validates FERNme's **memory mechanics** (storage, reinforcement, decay, confidence,
drift, salience, flat cost), not an extraction model. A billed Mem0 (LLM) head-to-head is
the remaining open comparison.
