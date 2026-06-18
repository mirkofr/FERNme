"""Self-tuning forgetting (#6) — learn the decay rate instead of hardcoding it.

Competitors hardcode decay (HippoGraph: half-life=30d). FERN can search candidate
rates against an objective and pick the best for the actual conditions — and it
*adapts*: more preference drift -> faster forgetting; stationary -> keep more.
Only possible because FERN has the population + an outcome/recall signal to
optimize against.

In production you'd tune against a site's own held-out outcomes; here the
objective is the drift simulator (a faithful proxy)."""
from __future__ import annotations
import random, statistics
from dataclasses import replace
from .config import DEFAULT
from .core.graph import UserGraph, AssocGraph, Event
from .write import Catalog, map_event, observe, decay
from .eval.drift import _clean_catalog, _prefs, _items, _topk, _prec, HALF1, HALF2


def _score(lam: float, drift: bool, seeds: int = 2, n_old: int = 60,
           n_new: int = 25, k: int = 5, users: int = 15) -> float:
    cfg = replace(DEFAULT, lam=lam, floor=0.5)
    out = []
    for seed in range(seeds):
        rng = random.Random(seed); cat_d = _clean_catalog(seed); cat = Catalog(cat_d)
        for u in range(users):
            old = _prefs(HALF1, rng)
            new = _prefs(HALF2, rng) if drift else old      # stationary -> tastes unchanged
            ug, ag = UserGraph("s", f"u{u}"), AssocGraph("s")
            seq = _items(old, cat_d, rng, n_old) + _items(new, cat_d, rng, n_new)
            for t, it in enumerate(seq):
                ev = Event("s", f"u{u}", float(t), "p", {"item_id": it})
                observe(ug, ag, ev, map_event(ev, cat), cfg); decay(ug, now=float(t), cfg=cfg)
            truth = _topk(new, k)
            top = [a for a, _ in sorted(ug.edges.items(), key=lambda kv: -kv[1].weight)[:k]]
            out.append(_prec(top, truth, k))
    return statistics.mean(out)


def tune_decay(candidates=(0.0, 0.05, 0.1, 0.2, 0.4), drift: bool = True,
               seeds: int = 2) -> dict:
    scores = {lam: _score(lam, drift, seeds) for lam in candidates}
    best = max(scores, key=scores.get)
    return {"best_lam": best, "scores": {round(k, 3): round(v, 3) for k, v in scores.items()}}
