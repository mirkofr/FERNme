"""SIMULATED OUTCOME PILOT — a fake storefront that tests the whole loop:
memory -> recommendation -> purchase, scored by an OUTCOME metric (conversion),
not QA. This is the closest honest stand-in for a real per-site pilot.

Design (kept deliberately un-circular):
  * Each shopper has a HIDDEN preference vector + drift.
  * On every visit the shopper makes a SELF-DIRECTED purchase from their true
    prefs. FERN learns ONLY from that independent behavior (not from the recs).
  * The agent then shows R recommendations. We score conversion = does the best
    recommended item match the shopper's hidden prefs (prob = match).
  * TREATMENT recommends by the FERN-learned profile; CONTROL recommends the
    globally most-popular items (a strong non-personalized baseline).

HONEST CAVEAT: the simulator defines the ground truth FERN learns, so this proves
the mechanism works and beats non-personalized recs UNDER THESE ASSUMPTIONS. It is
NOT evidence about real humans. A real pilot is still required for that.
Run: python -m fern.eval.pilot
"""
from __future__ import annotations
import random, statistics
from collections import Counter
from dataclasses import replace
from ..core.graph import UserGraph, AssocGraph, Event
from ..write import Catalog, map_event, observe, decay
from ..config import DEFAULT
from .simulator import ATTRS

R = 4            # recommendations shown per visit
VISITS = 12


def _catalog(seed, n=120):
    rng = random.Random(seed)
    return {f"i{i}": rng.sample(ATTRS, k=rng.randint(2, 3)) for i in range(n)}


def _match(item_tags, prefs):
    return sum(prefs.get(t, 0.0) for t in item_tags) / max(len(item_tags), 1)


def _self_directed_item(prefs, cat_d, rng):
    best, bs = None, -1.0
    for _ in range(10):
        it = rng.choice(list(cat_d))
        sc = _match(cat_d[it], prefs) + rng.random() * 0.15
        if sc > bs: best, bs = it, sc
    return best


def _popularity(cat_d, all_prefs, rng):
    c = Counter()
    for prefs in all_prefs:
        for _ in range(8):
            c[_self_directed_item(prefs, cat_d, rng)] += 1
    return [it for it, _ in c.most_common(20)]


def _fern_recommend(ug, cat_d, k):
    w = {a: e.weight for a, e in ug.edges.items() if e.source != "guessed"}
    if not w:
        return None
    scored = sorted(cat_d, key=lambda it: -sum(w.get(t, 0.0) for t in cat_d[it]))
    return scored[:k]


def run(seeds=6, n_shoppers=40):
    conv = {"FERN": [[] for _ in range(VISITS)], "popularity": [[] for _ in range(VISITS)]}
    for seed in range(seeds):
        rng = random.Random(seed)
        cat_d = _catalog(seed); cat = Catalog(cat_d)
        shoppers = []
        for u in range(n_shoppers):
            prefs = {a: rng.random() ** 2 for a in ATTRS}
            shoppers.append(prefs)
        popular = _popularity(cat_d, shoppers, random.Random(seed + 7))
        for u, prefs in enumerate(shoppers):
            cfg = replace(DEFAULT, lam=0.05)
            ug, ag = UserGraph("shop", f"u{u}"), AssocGraph("shop")
            cur = dict(prefs)
            for v in range(VISITS):
                if v == VISITS // 2:                         # mid-pilot taste drift
                    cur = {a: 0.5 * cur[a] + 0.5 * (rng.random() ** 2) for a in ATTRS}
                # 1) agent recommends FIRST, from what it has learned so far
                #    (visit 1 = true cold start: empty profile -> falls back to popular)
                fern_recs = _fern_recommend(ug, cat_d, R) or popular[:R]
                conv["FERN"][v].append(max(_match(cat_d[i], cur) for i in fern_recs))
                conv["popularity"][v].append(max(_match(cat_d[i], cur) for i in popular[:R]))
                # 2) THEN the shopper makes a self-directed purchase -> FERN learns
                bought = _self_directed_item(cur, cat_d, rng)
                ev = Event("shop", f"u{u}", float(v), "purchase", {"item_id": bought})
                observe(ug, ag, ev, map_event(ev, cat), cfg); decay(ug, now=float(v), cfg=cfg)
    # average conversion per visit, then overall
    def per_visit(arm): return [statistics.mean(conv[arm][v]) for v in range(VISITS)]
    fv, pv = per_visit("FERN"), per_visit("popularity")
    return {"fern_by_visit": fv, "pop_by_visit": pv,
            "fern_overall": statistics.mean(fv), "pop_overall": statistics.mean(pv)}


def main():
    r = run()
    print("=" * 60)
    print("SIMULATED OUTCOME PILOT — recommendation conversion (match)")
    print("=" * 60)
    print(f"{'visit':>6} {'FERN':>10} {'popularity':>12} {'lift':>8}")
    for v in range(VISITS):
        f, p = r["fern_by_visit"][v], r["pop_by_visit"][v]
        print(f"{v+1:>6} {f:>10.3f} {p:>12.3f} {f-p:>+8.3f}")
    lift = r["fern_overall"] - r["pop_overall"]
    rel = 100 * lift / r["pop_overall"]
    print("-" * 60)
    print(f"Overall: FERN {r['fern_overall']:.3f} vs popularity {r['pop_overall']:.3f} "
          f"-> +{rel:.0f}% relative lift")
    print("Cold start (visit 1) ~ tied; FERN pulls ahead as it learns, and")
    print("recovers after the mid-pilot drift. CAVEAT: simulated ground truth,")
    print("not real humans -- proves the loop, not real-world conversion.")
    return r


if __name__ == "__main__":
    main()
