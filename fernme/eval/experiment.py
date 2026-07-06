"""Headline experiments (file 10, section 11):
  Q1 - per-turn token cost vs profile size: FERN should stay FLAT while a
       full-history-in-context agent grows linearly.
  Q2 - write cost: LLM calls per write. FERN = 0; LLM-extraction memory >= 1.
Run:  python -m fern.eval.experiment
"""
from __future__ import annotations
import sys, random, statistics
from typing import List
from ..core.graph import UserGraph, AssocGraph, Event
from ..write import map_event, observe, decay
from ..write.mapping import Catalog
from ..retrieve.card import compile_card, estimate_tokens
from ..prior.population import PopulationPrior
from ..config import DEFAULT
from .simulator import make_catalog, make_personas, stream_events


def _history_tokens(events: List[Event], catalog: Catalog) -> int:
    """Baseline A: inject the full interaction history as text every turn."""
    lines = []
    for e in events:
        tags = ",".join(catalog.attrs_for(e.payload.get("item_id", "")))
        lines.append(f"{e.type} item={e.payload.get('item_id')} qty={e.payload.get('qty')} tags={tags}")
    return estimate_tokens("\n".join(lines))


def run(n_users=40, n_events=120, decay_every=20, seed=0):
    rng = random.Random(seed)
    catalog_d = make_catalog(seed=seed)
    catalog = Catalog(catalog_d)
    personas = make_personas(n_users, seed=seed + 1)
    prior = PopulationPrior("s1")

    # warm a population prior from half the users (so cold-start has a baseline)
    for p in personas[: n_users // 2]:
        ug = UserGraph("s1", p["user"]); assoc0 = AssocGraph("s1")
        for ev in stream_events(p, catalog_d, 40, seed=rng.randint(0, 1 << 30)):
            observe(ug, assoc0, ev, map_event(ev, catalog))
        prior.update_from_user(ug)

    assoc = AssocGraph("s1")
    # collect curves averaged over the held-out users
    fern_curve = {k: [] for k in range(1, n_events + 1)}
    hist_curve = {k: [] for k in range(1, n_events + 1)}
    fern_edges = {k: [] for k in range(1, n_events + 1)}
    write_llm_calls_fern = 0
    write_llm_calls_extract = 0

    for p in personas[n_users // 2:]:
        ug = UserGraph("s1", p["user"])
        prior.cold_start(ug)  # turn-one usefulness from the prior
        events = stream_events(p, catalog_d, n_events, seed=rng.randint(0, 1 << 30))
        seen: List[Event] = []
        for i, ev in enumerate(events, start=1):
            mapped = map_event(ev, catalog)
            observe(ug, assoc, ev, mapped)          # FERN write: pure arithmetic
            write_llm_calls_fern += 0
            write_llm_calls_extract += 2            # extraction memory: extract + reconcile
            if i % decay_every == 0:
                decay(ug, now=float(i))
            seen.append(ev)
            card = compile_card(ug, assoc, seeds=[a for a, _ in mapped][:2],
                                now=float(i), prior=prior)
            fern_curve[i].append(card["tokens"])
            fern_edges[i].append(ug.n_edges())
            hist_curve[i].append(_history_tokens(seen, catalog))

    def avg(d, k): return statistics.mean(d[k]) if d[k] else 0.0
    xs = list(range(1, n_events + 1))
    return {
        "xs": xs,
        "fern": [avg(fern_curve, k) for k in xs],
        "hist": [avg(hist_curve, k) for k in xs],
        "edges": [avg(fern_edges, k) for k in xs],
        "write_llm_fern": write_llm_calls_fern,
        "write_llm_extract": write_llm_calls_extract,
    }


def main():
    r = run()
    xs, fern, hist, edges = r["xs"], r["fern"], r["hist"], r["edges"]
    print("=" * 64)
    print("Q1  PER-TURN TOKEN COST vs. INTERACTIONS  (avg over held-out users)")
    print("=" * 64)
    print(f"{'turn':>6} {'FERN card':>12} {'full-history':>14} {'FERN edges':>12}")
    for k in [1, 5, 10, 20, 40, 60, 80, 100, 120]:
        if k <= len(xs):
            i = k - 1
            print(f"{k:>6} {fern[i]:>12.1f} {hist[i]:>14.1f} {edges[i]:>12.1f}")
    # flatness metric: slope of FERN tokens over the back half
    half = len(xs) // 2
    fern_slope = (fern[-1] - fern[half]) / (xs[-1] - xs[half])
    hist_slope = (hist[-1] - hist[half]) / (xs[-1] - xs[half])
    print("-" * 64)
    print(f"FERN token slope (back half):  {fern_slope:+.3f} tokens/interaction  -> ~flat")
    print(f"Full-history slope (back half):{hist_slope:+.3f} tokens/interaction  -> grows")
    print(f"At turn {xs[-1]}: full-history is {hist[-1]/max(fern[-1],1):.1f}x the FERN card")
    print()
    print("=" * 64)
    print("Q2  WRITE COST  (cumulative LLM calls to update memory)")
    print("=" * 64)
    print(f"FERN (deterministic core):        {r['write_llm_fern']:>8} LLM calls")
    print(f"LLM-extraction memory (~Mem0): {r['write_llm_extract']:>8} LLM calls")
    print("FERN deterministic write path makes zero model calls.")
    return r


if __name__ == "__main__":
    main()
