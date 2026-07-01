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


def _score_half_lives(half_lives: dict, drift: bool, seeds: int = 2,
                      n_old: int = 60, n_new: int = 25, k: int = 5,
                      users: int = 15, lam: float = 0.10) -> float:
    cfg = replace(DEFAULT, resolution=True, volatility_half_lives=half_lives,
                  lam=lam, floor=0.5)
    out = []
    for seed in range(seeds):
        rng = random.Random(seed); cat_d = _clean_catalog(seed); cat = Catalog(cat_d)
        for u in range(users):
            old = _prefs(HALF1, rng)
            new = _prefs(HALF2, rng) if drift else old
            ug, ag = UserGraph("s", f"u{u}"), AssocGraph("s")
            seq = _items(old, cat_d, rng, n_old) + _items(new, cat_d, rng, n_new)
            for t, it in enumerate(seq):
                ev = Event("s", f"u{u}", float(t), "p", {"item_id": it})
                observe(ug, ag, ev, map_event(ev, cat), cfg)
                decay(ug, now=float(t), cfg=cfg)
            truth = _topk(new, k)
            top = [a for a, _ in sorted(ug.edges.items(), key=lambda kv: -kv[1].weight)[:k]]
            out.append(_prec(top, truth, k))
    return statistics.mean(out)


def tune_volatility_half_lives(preference=(7.0, 14.0, 21.0),
                               volatile=(7.0, 14.0, 21.0),
                               association=(3.0, 4.0, 5.0, 7.0, 10.0, 14.0),
                               seeds: int = 2) -> dict:
    """Tune the classes exercised by the drift simulator.

    The simulator's catalog tags are unnamespaced, so they map to association.
    Keep association in the search or drift can regress even if preference is
    short.
    """
    base = dict(DEFAULT.volatility_half_lives)
    scores = {}
    for pref in preference:
        for vol in volatile:
            for assoc in association:
                half_lives = dict(base)
                half_lives["preference"] = pref
                half_lives["volatile"] = vol
                half_lives["association"] = assoc
                score = _score_half_lives(half_lives, drift=True, seeds=seeds)
                scores[(pref, vol, assoc)] = score
    best = max(scores, key=scores.get)
    return {
        "best": {
            "preference": best[0],
            "volatile": best[1],
            "association": best[2],
            "score": round(scores[best], 3),
        },
        "scores": {
            f"pref={k[0]},volatile={k[1]},association={k[2]}": round(v, 3)
            for k, v in sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
        },
    }


def tune_retention_half_lives(permanent=(3650.0, 7300.0),
                              slow=(120.0, 200.0, 365.0),
                              seeds: int = 2) -> dict:
    """Search only classes not exercised by drift, with drift classes pinned."""
    from .eval.retention import run as retention_run

    scores = {}
    base = dict(DEFAULT.volatility_half_lives)
    base["preference"] = 14.0
    base["volatile"] = 7.0
    base["association"] = 5.0
    for perm in permanent:
        for slow_days in slow:
            half_lives = dict(base)
            half_lives["permanent"] = perm
            half_lives["slow"] = slow_days
            cfg = replace(DEFAULT, resolution=True, volatility_half_lives=half_lives)
            result = retention_run(seeds=seeds, users=15, cfg_treatment=cfg)
            score = (
                result["permanent_above_floor_treatment"][0]
                + result["volatile_new_wins_treatment"][0]
                + result["slow_new_wins_treatment"][0]
            ) / 3.0
            scores[(perm, slow_days)] = score
    best = max(scores, key=scores.get)
    return {
        "best": {
            "permanent": best[0],
            "slow": best[1],
            "score": round(scores[best], 3),
        },
        "scores": {
            f"permanent={k[0]},slow={k[1]}": round(v, 3)
            for k, v in sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
        },
    }
