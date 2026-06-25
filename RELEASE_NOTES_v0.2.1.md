# FERNme v0.2.1 — recall latency fix

A focused patch. **No API or behavior change — pure performance.**

## The bug
Spreading-activation recall called `AssocGraph.neighbors()`, which scanned *every*
association edge for every node on every hop — O(nodes × edges × hops). That pushed
recall past 200ms once a user had a few hundred memories. (Caught by a good question on
r/AI_Agents about p95 read latency on a hot path.)

## The fix
`AssocGraph` now keeps an adjacency index (`_adj`), built lazily and kept in sync on
writes, so `neighbors()` is O(degree) instead of O(all edges).

## Measured (synthetic, pure-Python, single graph)

| user memories | assoc edges | p95 before | p95 after |
|---|---|---|---|
| 200 | 5,000 | 222 ms | 2.4 ms |
| 1,000 | 50,000 | — | 30 ms |

~90× faster at 200 memories; ~30ms p95 at 1,000 memories over a 50k-edge graph — usable
for a real-time agent.

## Also
- `tests/test_perf_recall.py` — index correctness + a latency-ceiling regression guard.
- `docs/v0.3_scaling.md` — documents the one case the index does **not** solve (a single
  user with tens of thousands of their *own* memories still climbs back toward 200ms,
  because recall wakes every stored memory) and the **bounded-working-set** plan for it.
  Honest about built vs. designed.

**Full suite: 99 tests passing.** · **Code:** https://github.com/mirkofr/FERNme
