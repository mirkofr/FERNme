"""Synthetic typed-entity micro-eval.

Run: python -m fernme.eval.entities
"""
from __future__ import annotations

import random
import statistics
from dataclasses import replace

from ..config import DEFAULT
from ..service import FernService

ALIASES = ("person:dana", "person:dana-reyes", "person:mrs-reyes")
SITE = "demo"
USER = "alex"


def _observe_many(svc: FernService, attr: str, count: int, ts_start: float):
    for i in range(count):
        svc.observe(SITE, USER, "note", {"tags": [attr]}, ts=ts_start + i * 0.001)


def _fixture(seed: int, entity_aggregation: bool):
    rng = random.Random(seed)
    cfg = replace(DEFAULT, top_n=8, entity_aggregation=entity_aggregation)
    svc = FernService(":memory:", cfg=cfg)
    svc.consent(SITE, USER, True)

    rows = [(alias, 3) for alias in ALIASES]
    rows.extend([
        ("topic:market-entry", 4 + rng.randint(0, 1)),
        ("person:felix-tan", 2 + rng.randint(0, 1)),
        ("org:orbit-labs", 2),
        ("project:northwind-demo", 1 + rng.randint(0, 1)),
    ])
    rng.shuffle(rows)

    ts = 0.0
    for attr, count in rows:
        _observe_many(svc, attr, count, ts)
        ts += 1.0

    dana = svc.entity_create(SITE, USER, "person", "Dana Reyes")
    for alias in ALIASES:
        svc.entity_link_alias(SITE, USER, dana, alias)

    card = svc.card(SITE, USER, now=0.0)
    links = [link["attr"] for link in card["links"]]
    ranks = [links.index(alias) + 1 for alias in ALIASES if alias in links]
    return {
        "rank": min(ranks) if ranks else None,
        "top_attr": links[0] if links else "",
        "wire": card["wire"],
    }


def run(seeds: int = 6):
    rows = []
    for seed in range(seeds):
        off = _fixture(seed, entity_aggregation=False)
        on = _fixture(seed, entity_aggregation=True)
        rows.append({
            "seed": seed,
            "off_rank": off["rank"],
            "on_rank": on["rank"],
            "off_top_attr": off["top_attr"],
            "on_top_attr": on["top_attr"],
        })
    off_ranks = [row["off_rank"] for row in rows if row["off_rank"] is not None]
    on_ranks = [row["on_rank"] for row in rows if row["on_rank"] is not None]
    return {
        "rows": rows,
        "off_mean_rank": statistics.mean(off_ranks),
        "on_mean_rank": statistics.mean(on_ranks),
    }


def _rank_text(value):
    return "n/a" if value is None else str(value)


def main():
    result = run()
    print("=" * 76)
    print("SYNTHETIC ENTITY A2 MICRO-EVAL -- alias-fragmentation dilution")
    print("(fictional fixture; 6 seeds; rank 1 is best; lower is better)")
    print("=" * 76)
    print("seed | off_rank | on_rank | off_top_attr        | on_top_attr")
    print("-----|----------|---------|---------------------|----------------")
    for row in result["rows"]:
        print(
            f"{row['seed']:>4} | {_rank_text(row['off_rank']):>8} | "
            f"{_rank_text(row['on_rank']):>7} | "
            f"{row['off_top_attr']:<19} | {row['on_top_attr']}"
        )
    print("-----|----------|---------|---------------------|----------------")
    print(
        f"mean | {result['off_mean_rank']:>8.2f} | "
        f"{result['on_mean_rank']:>7.2f} | "
        "aggregation off    | aggregation on"
    )
    print("-" * 76)
    print("Read: with aggregation off, one alias fragment must rank on its own;")
    print("with aggregation on, linked aliases lift the entity together.")
    return result


if __name__ == "__main__":
    main()
