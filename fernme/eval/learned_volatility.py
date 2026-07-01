"""Synthetic personalized-staleness eval for Option B.

Run: python -m fernme.eval.learned_volatility
"""
from __future__ import annotations

import random
import statistics
from dataclasses import replace

from ..config import DEFAULT
from ..core.graph import Edge
from ..resolution import effective_half_life_days, needs_verify

NOW = 1000.0
ATTR = "employer:current"


def _fast_edge(rng: random.Random) -> Edge:
    first = rng.uniform(0.0, 120.0)
    count = rng.randint(5, 10)
    last_changed = rng.uniform(780.0, 900.0)
    return Edge(
        weight=5.0,
        confidence=0.9,
        hits=5,
        last_reinforced=last_changed,
        provenance="stated",
        change_count=count,
        first_seen_ts=first,
        last_changed_ts=last_changed,
        last_change_counted_ts=last_changed,
    )


def _stable_edge(rng: random.Random) -> Edge:
    first = rng.uniform(0.0, 80.0)
    return Edge(
        weight=5.0,
        confidence=0.9,
        hits=5,
        last_reinforced=first,
        provenance="stated",
        change_count=0,
        first_seen_ts=first,
    )


def _rows(seed: int, users: int):
    rng = random.Random(seed)
    prior_cfg = replace(DEFAULT, learned_volatility=False, verify_age_enabled=True)
    learned_cfg = replace(DEFAULT, learned_volatility=True, verify_age_enabled=True)
    rows = {
        "fast_half_life_prior": [],
        "fast_half_life_learned": [],
        "stable_half_life_prior": [],
        "stable_half_life_learned": [],
        "fast_age_halflives_prior": [],
        "fast_age_halflives_learned": [],
        "stable_age_halflives_prior": [],
        "stable_age_halflives_learned": [],
        "directional_success": [],
        "cold_start_delta": [],
    }
    for _ in range(users):
        fast = _fast_edge(rng)
        stable = _stable_edge(rng)
        cold = Edge(weight=5.0, confidence=0.9, hits=5, last_reinforced=900.0)
        fast_prior = effective_half_life_days(ATTR, fast, NOW, prior_cfg)
        fast_learned = effective_half_life_days(ATTR, fast, NOW, learned_cfg)
        stable_prior = effective_half_life_days(ATTR, stable, NOW, prior_cfg)
        stable_learned = effective_half_life_days(ATTR, stable, NOW, learned_cfg)
        fast_age_prior = needs_verify(ATTR, fast, NOW, prior_cfg)["age_halflives"]
        fast_age_learned = needs_verify(ATTR, fast, NOW, learned_cfg)["age_halflives"]
        stable_age_prior = needs_verify(ATTR, stable, NOW, prior_cfg)["age_halflives"]
        stable_age_learned = needs_verify(ATTR, stable, NOW, learned_cfg)["age_halflives"]
        cold_prior = effective_half_life_days(ATTR, cold, NOW, prior_cfg)
        cold_learned = effective_half_life_days(ATTR, cold, NOW, learned_cfg)
        rows["fast_half_life_prior"].append(fast_prior)
        rows["fast_half_life_learned"].append(fast_learned)
        rows["stable_half_life_prior"].append(stable_prior)
        rows["stable_half_life_learned"].append(stable_learned)
        rows["fast_age_halflives_prior"].append(fast_age_prior)
        rows["fast_age_halflives_learned"].append(fast_age_learned)
        rows["stable_age_halflives_prior"].append(stable_age_prior)
        rows["stable_age_halflives_learned"].append(stable_age_learned)
        rows["directional_success"].append(
            float(fast_learned < fast_prior and stable_learned > stable_prior
                  and fast_age_learned > fast_age_prior
                  and stable_age_learned < stable_age_prior)
        )
        rows["cold_start_delta"].append(abs(cold_learned - cold_prior))
    return rows


def _summarize(rows: dict[str, list[float]]) -> dict[str, tuple[float, float]]:
    return {k: (statistics.mean(v), statistics.pstdev(v)) for k, v in rows.items()}


def run(seeds: int = 6, users: int = 40):
    rows = {}
    for seed in range(seeds):
        per = _rows(seed, users)
        for key, vals in per.items():
            rows.setdefault(key, []).append(statistics.mean(vals))
    return _summarize(rows)


def _print_metric(name: str, result):
    mean, sd = result[name]
    print(f"  {name:<36} {mean:.3f} +/- {sd:.3f}")


def main():
    result = run()
    print("=" * 76)
    print("SYNTHETIC LEARNED VOLATILITY EVAL -- personalized staleness prior")
    print("(6 seeds x 40 users; no outside corroboration, no silent-change detection)")
    print("=" * 76)
    for key in (
        "fast_half_life_prior",
        "fast_half_life_learned",
        "stable_half_life_prior",
        "stable_half_life_learned",
        "fast_age_halflives_prior",
        "fast_age_halflives_learned",
        "stable_age_halflives_prior",
        "stable_age_halflives_learned",
        "directional_success",
        "cold_start_delta",
    ):
        _print_metric(key, result)
    print("-" * 76)
    print("Read: learned volatility should shorten fast changers, lengthen stable")
    print("users, and leave cold-start edges at the class prior.")
    return result


if __name__ == "__main__":
    main()
