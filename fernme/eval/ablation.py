"""ABLATION - does the population PRIOR (differential encoding) help at cold start?
Compares FERN with prior cold-start vs FERN with an empty start, at early turns,
on a population that shares structure. This isolates the load-bearing claim from
file 10/09. Run: python -m fern.eval.ablation"""
from __future__ import annotations
import statistics
from ..core.graph import UserGraph, AssocGraph
from ..write import Catalog, map_event, observe
from ..prior.population import PopulationPrior
from ..config import DEFAULT
from .simulator import make_catalog, make_personas, stream_events


def _true_topk(p, k): return set(a for a, _ in sorted(p["prefs"].items(), key=lambda kv: -kv[1])[:k])
def _prec(pred, truth, k): return len(set(pred) & truth) / float(k)


def _topk_from_graph(ug, k):
    # known (real) edges first, then guessed fill remaining slots -> prior never
    # displaces real signal, only fills gaps.
    def key(kv):
        a, e = kv
        real = 0 if e.source == "guessed" else 1
        return (real, e.weight)
    return [a for a, _ in sorted(ug.edges.items(), key=key, reverse=True)[:k]]


def run(seeds=5, n_train=60, n_test=40, turns=(1, 2, 3, 5, 10), k=5, shared=0.6):
    with_prior = {t: [] for t in turns}
    no_prior = {t: [] for t in turns}
    for seed in range(seeds):
        cat_d = make_catalog(seed=seed); cat = Catalog(cat_d)
        train = make_personas(n_train, seed=seed + 1, shared=shared)
        test = make_personas(n_test, seed=seed + 500, shared=shared)
        # build the population prior from the training users
        prior = PopulationPrior("s")
        for p in train:
            ug, ag = UserGraph("s", p["user"]), AssocGraph("s")
            for ev in stream_events(p, cat_d, 40, seed=seed * 7 + 1):
                observe(ug, ag, ev, map_event(ev, cat))
            prior.update_from_user(ug)
        # for each test user, measure precision@k at early turns, both ways
        for p in test:
            truth = _true_topk(p, k)
            evs = stream_events(p, cat_d, max(turns), seed=seed * 13 + 3)
            for t in turns:
                ugp, agp = UserGraph("s", p["user"]), AssocGraph("s")
                prior.cold_start(ugp)                       # WITH prior
                ugn, agn = UserGraph("s", p["user"]), AssocGraph("s")  # WITHOUT
                for ev in evs[:t]:
                    observe(ugp, agp, ev, map_event(ev, cat))
                    observe(ugn, agn, ev, map_event(ev, cat))
                with_prior[t].append(_prec(_topk_from_graph(ugp, k), truth, k))
                no_prior[t].append(_prec(_topk_from_graph(ugn, k), truth, k))
    summ = lambda d, t: (statistics.mean(d[t]), statistics.pstdev(d[t]))
    return {t: {"with_prior": summ(with_prior, t), "no_prior": summ(no_prior, t)} for t in turns}


def main():
    r = run()
    print("=" * 60)
    print("DIFFERENTIAL-ENCODING ABLATION — precision@5 at early turns")
    print("(population shares structure; 5 seeds x 40 test users)")
    print("=" * 60)
    print(f"{'turn':>5} {'with prior':>16} {'no prior':>16} {'gain':>7}")
    for t, d in r.items():
        wp, npr = d["with_prior"][0], d["no_prior"][0]
        print(f"{t:>5} {wp:>10.3f}+/-{d['with_prior'][1]:.2f} {npr:>10.3f}+/-{d['no_prior'][1]:.2f} {wp-npr:>+7.3f}")
    print("-" * 60)
    print("Read: the prior should help most at turn 1-2 (cold start) and wash")
    print("out as individual data arrives. If gain ~0, demote the claim (per file 10).")
    return r


if __name__ == "__main__":
    main()
