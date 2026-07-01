"""Synthetic long-horizon retention eval.

Run: python -m fernme.eval.retention
"""
from __future__ import annotations

import random
import statistics
from dataclasses import replace

from ..confidence import compute
from ..config import DEFAULT
from ..core.graph import AssocGraph, Edge, UserGraph
from ..retrieve.card import compile_card
from ..write.hebbian import decay

HORIZON = 700.0
PERMANENT = ("allergy:peanut", "name:elena", "birthday:apr-3")


def _edge(rng: random.Random, weight: float, last: float, *,
          source: str = "known", provenance: str = "stated",
          salience: float = 0.0, hits: int = 5) -> Edge:
    return Edge(
        weight=weight * rng.uniform(0.95, 1.05),
        confidence=0.9,
        source=source,
        last_reinforced=last,
        hits=hits,
        salience=salience,
        provenance=provenance,
    )


def _profile(seed: int, user: int) -> UserGraph:
    rng = random.Random(seed * 1009 + user)
    ug = UserGraph("s", f"u{user}")
    for attr in PERMANENT:
        ug.edges[attr] = _edge(rng, 5.0, 0.0, salience=DEFAULT.salience_identity)

    ug.edges["employer:oldco"] = _edge(
        rng, 7.0, 0.0, source="superseded", salience=DEFAULT.salience_identity)
    ug.edges["employer:newco"] = _edge(
        rng, 5.0, 620.0, salience=DEFAULT.salience_identity)

    ug.edges["project:atlas"] = _edge(rng, 7.0, 640.0, provenance="inferred")
    ug.edges["project:zephyr"] = _edge(rng, 5.0, 695.0, provenance="stated")
    for idx in range(4):
        ug.edges[f"topic:noise-{idx}"] = _edge(
            rng, rng.uniform(1.0, 4.0), rng.uniform(0.0, 680.0),
            provenance="inferred", salience=0.0, hits=2)
    return ug


def _clone(ug: UserGraph) -> UserGraph:
    return UserGraph(ug.site, ug.user,
                     {a: Edge(**e.__dict__) for a, e in ug.edges.items()})


def _decayed(ug: UserGraph, cfg) -> UserGraph:
    out = _clone(ug)
    decay(out, now=HORIZON, cfg=cfg)
    return out


def _rows_for(ug: UserGraph, cfg) -> dict[str, float]:
    decayed = _decayed(ug, cfg)
    card = compile_card(decayed, AssocGraph("s"),
                        ["who am I?", "what must not be forgotten?"],
                        now=HORIZON, cfg=cfg)
    links = {link["attr"] for link in card["links"]}
    permanent_present = [attr for attr in PERMANENT if attr in decayed.edges]
    permanent_conf = [
        compute(decayed.edges[attr], HORIZON, cfg, attr=attr)
        for attr in permanent_present
    ]
    old_employer = decayed.edges.get("employer:oldco")
    new_employer = decayed.edges.get("employer:newco")
    stale_project = decayed.edges.get("project:atlas")
    fresh_project = decayed.edges.get("project:zephyr")
    old_w = old_employer.weight if old_employer else 0.0
    new_w = new_employer.weight if new_employer else 0.0
    stale_w = stale_project.weight if stale_project else 0.0
    fresh_w = fresh_project.weight if fresh_project else 0.0

    return {
        "permanent_in_card": len(set(PERMANENT) & links) / float(len(PERMANENT)),
        "permanent_present": len(permanent_present) / float(len(PERMANENT)),
        "permanent_above_floor": sum(
            decayed.edges[attr].weight > cfg.floor for attr in permanent_present
        ) / float(len(PERMANENT)),
        "permanent_high_conf": sum(c >= cfg.conf_high for c in permanent_conf)
        / float(len(PERMANENT)),
        "slow_new_wins": 1.0 if new_w > old_w and "employer:newco" in links else 0.0,
        "old_slow_weight": old_w,
        "stale_volatile_weight": stale_w,
        "volatile_new_wins": 1.0 if fresh_w > stale_w else 0.0,
    }


def _summarize(rows: dict[str, list[float]]) -> dict[str, tuple[float, float]]:
    return {k: (statistics.mean(v), statistics.pstdev(v)) for k, v in rows.items()}


def run(seeds: int = 6, users: int = 30, cfg_control=None, cfg_treatment=None):
    control = cfg_control or replace(DEFAULT, resolution=False)
    treatment = cfg_treatment or replace(DEFAULT, resolution=True)
    rows = {}
    for key in (
        "permanent_in_card",
        "permanent_present",
        "permanent_above_floor",
        "permanent_high_conf",
        "slow_new_wins",
        "old_slow_weight",
        "stale_volatile_weight",
        "volatile_new_wins",
    ):
        rows[f"{key}_control"] = []
        rows[f"{key}_treatment"] = []

    for seed in range(seeds):
        per = {k: [] for k in rows}
        for user in range(users):
            ug = _profile(seed, user)
            for label, cfg in (("control", control), ("treatment", treatment)):
                metrics = _rows_for(ug, cfg)
                for key, value in metrics.items():
                    per[f"{key}_{label}"].append(value)
        for key in rows:
            rows[key].append(statistics.mean(per[key]))
    return _summarize(rows)


def _print_metric(name: str, result):
    mean, sd = result[name]
    print(f"  {name:<36} {mean:.3f} +/- {sd:.3f}")


def main():
    result = run()
    print("=" * 76)
    print("SYNTHETIC RETENTION EVAL -- long-horizon class-targeted retention")
    print("(6 seeds x 30 users; 700 simulated days; control flat vs treatment volatility)")
    print("=" * 76)
    for key in (
        "permanent_in_card_control",
        "permanent_in_card_treatment",
        "permanent_present_control",
        "permanent_present_treatment",
        "permanent_above_floor_control",
        "permanent_above_floor_treatment",
        "permanent_high_conf_control",
        "permanent_high_conf_treatment",
        "slow_new_wins_control",
        "slow_new_wins_treatment",
        "old_slow_weight_control",
        "old_slow_weight_treatment",
        "stale_volatile_weight_control",
        "stale_volatile_weight_treatment",
        "volatile_new_wins_control",
        "volatile_new_wins_treatment",
    ):
        _print_metric(key, result)
    print("-" * 76)
    print("Read: treatment should keep permanent facts above floor, fade stale volatile")
    print("facts, and let changed slow facts prefer the new value.")
    return result


if __name__ == "__main__":
    main()
