"""CONTEXT — the same user wants different things in different contexts (e.g.
weekday vs weekend). FERN seeds spreading activation with the current context and
recovers the context-relevant slice; a context-blind frequency counter returns the
global top and can't condition on 'now'. Run: python -m fern.eval.context"""
from __future__ import annotations
import statistics, random
from ..core.graph import UserGraph, AssocGraph, Event
from ..write import Catalog, map_event, observe
from ..retrieve.activation import ranked_attrs
from .simulator import ATTRS
from .baselines import frequency_topk

SET_A, SET_B = ATTRS[:5], ATTRS[5:10]


def _prec(pred, truth, k):
    pred = [a for a in pred if not a.startswith("ctx:")]
    return len(set(pred[:k]) & truth) / float(k)


def run(seeds=6, n_each=40, k=3):
    res = {"FERN (context-seeded)": [], "FERN (no context)": [], "frequency (blind)": []}
    for seed in range(seeds):
        rng = random.Random(seed)
        per = {m: [] for m in res}
        for u in range(30):
            ug, ag = UserGraph("s", f"u{u}"), AssocGraph("s"); evs = []
            t = 0
            for _ in range(n_each):
                for ctx, st in (("ctx:weekday", SET_A), ("ctx:weekend", SET_B)):
                    tags = [ctx] + rng.sample(st, 2)
                    ev = Event("s", f"u{u}", float(t), "purchase", {"tags": tags}); t += 1
                    observe(ug, ag, ev, map_event(ev, Catalog())); evs.append(ev)
            truth = set(SET_A)                       # we query in the weekday context
            seeded = ranked_attrs(ug, ag, ["ctx:weekday"], float(t), k=k + 2)
            blind = ranked_attrs(ug, ag, [], float(t), k=k + 2)
            per["FERN (context-seeded)"].append(_prec(seeded, truth, k))
            per["FERN (no context)"].append(_prec(blind, truth, k))
            per["frequency (blind)"].append(_prec(frequency_topk(evs, Catalog(), k + 2), truth, k))
        for m in res: res[m].append(statistics.mean(per[m]))
    return {m: (statistics.mean(v), statistics.pstdev(v)) for m, v in res.items()}


def main():
    r = run()
    print("=" * 58)
    print("CONTEXT — precision@3 for the weekday slice, queried in-context")
    print("(6 seeds x 30 users; weekday/weekend interleaved)")
    print("=" * 58)
    for m in ("FERN (context-seeded)", "FERN (no context)", "frequency (blind)"):
        print(f"  {m:<24} {r[m][0]:.3f} +/- {r[m][1]:.3f}")
    print("-" * 58)
    g = r["FERN (context-seeded)"][0] - r["frequency (blind)"][0]
    print(f"Context seeding lifts precision by {g:+.3f} over a blind counter")
    print("by spreading activation from the current context into its slice.")
    return r


if __name__ == "__main__":
    main()
