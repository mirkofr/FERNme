"""Recall must stay fast as the shared association graph grows.

Guards against the O(nodes x edges x hops) regression: before the adjacency
index, neighbors() scanned every association edge on every node every hop, so a
few hundred memories over a modest assoc graph blew past 200ms. With the index,
recall depends on degree, not total edge count. We assert a generous ceiling
(real indexed time is single-digit ms) so this is a regression tripwire, not a
flaky micro-benchmark.
"""
import random
import time
import statistics as st

from fernme.core.graph import UserGraph, AssocGraph, Edge
from fernme.retrieve.activation import spread
from fernme.config import DEFAULT


def _build(n_user=300, n_assoc=20000, deg=6, seed=0):
    rnd = random.Random(seed)
    ug = UserGraph("s", "u")
    attrs = [f"a{i}:v" for i in range(n_user)]
    for a in attrs:
        ug.edges[a] = Edge(weight=5.0, source="known", hits=2)
        ug.history[a] = [10.0, 20.0]
    ag = AssocGraph("s")
    universe = attrs + [f"g{i}:v" for i in range(n_assoc // deg)]
    for _ in range(n_assoc):
        x, y = rnd.choice(universe), rnd.choice(universe)
        if x != y:
            ag.edges[ag.key(x, y)] = rnd.uniform(0.1, 1.0)
    return ug, ag, attrs


def test_neighbors_index_matches_bruteforce():
    _, ag, attrs = _build(n_user=80, n_assoc=4000)

    def brute(a):
        out = []
        for (x, y), w in ag.edges.items():
            if x == a:
                out.append((y, w))
            elif y == a:
                out.append((x, w))
        return sorted(out)

    for a in attrs[:25]:
        assert sorted(ag.neighbors(a)) == brute(a)


def test_set_edge_keeps_index_in_sync():
    ag = AssocGraph("s")
    ag.set_edge("x:1", "y:1", 0.5)
    ag.set_edge("x:1", "z:1", 0.7)
    assert dict(ag.neighbors("x:1")) == {"y:1": 0.5, "z:1": 0.7}
    ag.set_edge("x:1", "y:1", 0.9)            # update existing weight
    assert dict(ag.neighbors("x:1"))["y:1"] == 0.9


def test_recall_latency_under_ceiling():
    ug, ag, attrs = _build()
    rnd = random.Random(1)
    times = []
    for _ in range(40):
        seed = rnd.choice(attrs)
        t0 = time.perf_counter()
        spread(ug, ag, [seed], now=60.0, cfg=DEFAULT)
        times.append((time.perf_counter() - t0) * 1000)
    p50 = st.median(times)
    # Indexed recall here is ~5-15ms; pre-index it was >200ms. Generous ceiling.
    assert p50 < 150.0, f"recall p50={p50:.1f}ms — adjacency index may have regressed"
