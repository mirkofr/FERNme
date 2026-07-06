# Benchmarks

> **Honest scope:** numbers are on synthetic or LLM-authored data unless stated otherwise. They validate mechanisms and surface failures; a real-human pilot is still pending.

## Unified harness

Reproduce the current cross-method table:

```bash
python -m fernme.eval.harness --seeds 6 --json reports/eval_harness.json
```

The unified harness covers static, abrupt drift, gradual drift, staleness, contextual, fragmented-entity, and outcome regimes across FERNme, entity flags, recency, frequency, and pure-Python BM25 Cabinet baselines.

## Suggest-and-approve canonicalization

```bash
python -m fernme.eval.canonicalization --seeds 6 --json reports/canonicalization.json
```

Synthetic planted duplicate-alias fixture. The queue is propose-only: no candidate changes memory truth unless a human accepts it.

## Propose-only enrichment

```bash
python -m fernme.eval.enrichment --seeds 6 --json reports/enrichment.json
```

Synthetic fictional relation-link fixture with a mock proposal source.

| metric | enrichment OFF | enrichment ON |
|---|---:|---:|
| precision | 0.000 +/- 0.000 | 1.000 +/- 0.000 |
| recall | 0.000 +/- 0.000 | 1.000 +/- 0.000 |
| suggestions | 0.000 +/- 0.000 | 2.000 +/- 0.000 |
| FERNme-initiated LLM calls | 0.000 +/- 0.000 | 1.000 +/- 0.000 |

This is a mock-source wiring check, not a real-model quality claim. Agent-driven proposals spend external agent tokens and leave `svc.llm_calls` at 0.