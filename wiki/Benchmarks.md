# Benchmarks

> **Honest scope:** all numbers are on **synthetic or LLM-authored** data, not real users. They validate the *mechanism* and surface failures; a real-human pilot is the pending next step. The Mem0 (LLM) head-to-head needs an API key and is not yet run.

## Closest to real — agentic ingestion of LLM-authored people
16 of 92 third-person profiles, read as **prose only** and remembered agentically, scored vs. hidden answer keys:

| metric | result |
|---|---|
| preference coverage vs. hidden key | 75% |
| communication style — formality | 100% |
| mood sign / mood arc | 94% / 100% |
| preference drift detected | 94% |
| injection attempts ignored | 100% |
| note → card compression | 7.3× |

*The "agent" is an LLM reading prose, so this reflects agent + engine together.*

## Cost (5 seeds)
| metric | FERNme | baseline |
|---|---|---|
| card size | 24.9 ± 0.5 tokens (flat) | full history grows linearly |
| at 120 interactions | 1× | 77× ± 1.3 larger |
| LLM calls per write | 0 | ~2 (extraction memory) |

## Recall quality — precision@5 (5 seeds × 40 users)
| regime | FERNme | frequency | recency |
|---|---|---|---|
| static | 0.74 | 0.74 | 0.47 |
| **drift** | **0.72** | 0.13 | 0.59 |
| **context** (P@3) | **0.62** | 0.51 (blind) | — |

FERNme is the only method strong in every regime: frequency can't forget (fails drift), recency is noisy (fails static).

## Cost / quality Pareto (per 1,000 interactions)
| strategy | quality | $/1k | vs Mem0 |
|---|---|---|---|
| FERNme-pure | 0.52 | $0.008 | 122× cheaper |
| FERNme+gated | 0.66 | $0.023 | 42× cheaper |
| FERNme+offline | 0.73 | $0.104 | 9× cheaper |
| full-history@120 | 0.82 | $0.59 (grows) | — |
| Mem0-style | 0.82 | $0.95 | 1× |

## Outcome pilot (simulated storefront)
+16% relative conversion lift vs. a popularity baseline; tied at cold start, pulls ahead as it learns, recovers through a mid-pilot taste shift.

## Reproduce
```bash
python -m fernme.eval.cost_variance | quality | drift | context | ablation | pilot | pareto
```
