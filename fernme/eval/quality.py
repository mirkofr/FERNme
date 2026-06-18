"""Q4 - RECALL QUALITY: does FERN's memory recover each user's TRUE preferences?
Measured against the simulator's ground-truth latent prefs, vs LLM-free baselines,
over multiple seeds with mean+/-std. Run: python -m fern.eval.quality"""
from __future__ import annotations
import statistics
from typing import List
from ..core.graph import UserGraph, AssocGraph, Event
from ..write import Catalog, map_event, observe
from .simulator import make_catalog, make_personas, stream_events, ATTRS
from .baselines import frequency_topk, recency_topk


def _true_topk(persona, k: int) -> set:
    return set(a for a, _ in sorted(persona["prefs"].items(), key=lambda kv: -kv[1])[:k])


def _fern_topk(events, catalog, k: int) -> List[str]:
    ug, ag = UserGraph("s", "u"), AssocGraph("s")
    for ev in events:
        observe(ug, ag, ev, map_event(ev, catalog))
    ranked = sorted(ug.edges.items(), key=lambda kv: -kv[1].weight)
    return [a for a, _ in ranked[:k]]


def _precision(pred: List[str], truth: set, k: int) -> float:
    return len(set(pred) & truth) / float(k)


def run(seeds=5, n_personas=40, n_events=80, k=5):
    rows = {"FERN": [], "frequency": [], "recency": []}
    for seed in range(seeds):
        cat_d = make_catalog(seed=seed); cat = Catalog(cat_d)
        personas = make_personas(n_personas, seed=seed + 100)
        per = {m: [] for m in rows}
        for p in personas:
            evs = stream_events(p, cat_d, n_events, seed=seed * 1000 + hash(p["user"]) % 999)
            truth = _true_topk(p, k)
            per["FERN"].append(_precision(_fern_topk(evs, cat, k), truth, k))
            per["frequency"].append(_precision(frequency_topk(evs, cat, k), truth, k))
            per["recency"].append(_precision(recency_topk(evs, cat, k), truth, k))
        for m in rows:
            rows[m].append(statistics.mean(per[m]))
    return {m: (statistics.mean(v), statistics.pstdev(v)) for m, v in rows.items()}


def main():
    r = run()
    print("=" * 56)
    print(f"RECALL QUALITY — precision@5 vs ground-truth prefs")
    print(f"(mean +/- std over 5 seeds x 40 users)")
    print("=" * 56)
    for m in ("FERN", "frequency", "recency"):
        mean, std = r[m]
        print(f"  {m:<12} {mean:.3f} +/- {std:.3f}")
    from .baselines import mem0_topk_if_available
    _, why = mem0_topk_if_available([], None, 5)
    print(f"  {'mem0 (LLM)':<12} {why}")
    print("-" * 56)
    print("Honest read: FERN should beat recency and match/modestly beat raw")
    print("frequency; the LLM baseline is the one to run locally with keys.")
    return r


if __name__ == "__main__":
    main()
