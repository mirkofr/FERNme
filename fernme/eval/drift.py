"""DRIFT — non-stationary preferences. Tastes move to a DISJOINT set partway
through, with more old history than new. A counter that can't forget stays stuck
on stale favorites; FERN's decay tracks the change. Shows FERN is strong on BOTH
regimes (static recall AND drift) where each baseline is strong on only one.
Run: python -m fern.eval.drift"""
from __future__ import annotations
import statistics, random
from dataclasses import replace
from ..core.graph import UserGraph, AssocGraph, Event
from ..write import Catalog, map_event, observe, decay
from ..config import DEFAULT
from .simulator import ATTRS
from .baselines import frequency_topk, recency_topk

HALF1, HALF2 = ATTRS[:7], ATTRS[7:]


def _clean_catalog(seed):
    rng = random.Random(seed); cat = {}
    for i in range(160):
        cat[f"i{i}"] = rng.sample(ATTRS, k=rng.randint(2, 3))   # ATTRS-only tags
    return cat


def _prefs(favored, rng):
    return {a: (0.6 + 0.4 * rng.random()) if a in favored else 0.0 for a in ATTRS}


def _topk(prefs, k): return set(a for a, _ in sorted(prefs.items(), key=lambda kv: -kv[1])[:k])
def _prec(pred, truth, k): return len(set(pred) & truth) / float(k)


def _items(prefs, cat_d, rng, n):
    keys = list(cat_d.keys()); out = []
    for _ in range(n):
        best, bs = None, -1.0
        for _ in range(8):
            it = rng.choice(keys)
            sc = sum(prefs.get(t, 0) for t in cat_d[it]) + rng.random() * 0.2
            if sc > bs: best, bs = it, sc
        out.append(best)
    return out


def run(seeds=6, n_old=60, n_new=25, k=5):
    res = {"FERN": [], "frequency": [], "recency": []}
    for seed in range(seeds):
        rng = random.Random(seed); cat_d = _clean_catalog(seed); cat = Catalog(cat_d)
        per = {m: [] for m in res}
        for u in range(30):
            old = _prefs(HALF1, rng); new = _prefs(HALF2, rng)     # disjoint shift
            cfg = replace(DEFAULT, lam=0.10, floor=0.5)
            ug, ag = UserGraph("s", f"u{u}"), AssocGraph("s"); evs = []
            seq = _items(old, cat_d, rng, n_old) + _items(new, cat_d, rng, n_new)
            for t, it in enumerate(seq):
                ev = Event("s", f"u{u}", float(t), "purchase", {"item_id": it})
                observe(ug, ag, ev, map_event(ev, cat), cfg); evs.append(ev)
                decay(ug, now=float(t), cfg=cfg)
            truth = _topk(new, k)
            fern = [a for a, _ in sorted(ug.edges.items(), key=lambda kv: -kv[1].weight)[:k]]
            per["FERN"].append(_prec(fern, truth, k))
            per["frequency"].append(_prec(frequency_topk(evs, cat, k), truth, k))
            per["recency"].append(_prec(recency_topk(evs, cat, k), truth, k))
        for m in res: res[m].append(statistics.mean(per[m]))
    return {m: (statistics.mean(v), statistics.pstdev(v)) for m, v in res.items()}


def main():
    r = run()
    print("=" * 58)
    print("DRIFT — precision@5 vs CURRENT taste after a disjoint shift")
    print("(6 seeds x 30 users; 60 old + 25 new interactions)")
    print("=" * 58)
    for m in ("FERN", "frequency", "recency"):
        print(f"  {m:<12} {r[m][0]:.3f} +/- {r[m][1]:.3f}")
    print("-" * 58)
    print(f"FERN beats frequency by {r['FERN'][0]-r['frequency'][0]:+.3f}: a counter")
    print("can't forget 60 old purchases; FERN's decay moves on.")
    return r


if __name__ == "__main__":
    main()
