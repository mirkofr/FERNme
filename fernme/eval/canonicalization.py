"""Synthetic eval for suggest-and-approve canonicalization.

Run:
    python -m fernme.eval.canonicalization --seeds 6 --json reports/canonicalization.json
"""
from __future__ import annotations

import argparse
import json
import random
import statistics
from pathlib import Path
from typing import Dict, List, Sequence, Tuple

from ..config import DEFAULT
from ..service import FernService
from ..store.sqlite_store import SQLiteStore

SITE = "canonicalization.example"
USER = "fictional-user"


def _observe_many(svc: FernService, attr: str, n: int, start: float) -> None:
    for i in range(n):
        svc.observe(SITE, USER, "note", {"tags": [attr]}, ts=start + i * 0.01)


def _fixture(seed: int):
    rng = random.Random(seed + 4100)
    svc = FernService(store=SQLiteStore(":memory:"))
    svc.track_style = False
    svc.consent(SITE, USER, True)
    planted = (
        ("person:dana-reyes", "person:dana_reyes"),
        ("person:felix-tan", "person:felix_tan"),
        ("org:northwind-ltd", "org:northwind_ltd"),
        ("project:cedar-demo", "project:cedar_demo"),
    )
    distractors = (
        "person:lina-reyes",
        "topic:board-update",
        "org:river-studio",
        "project:harbor-plan",
        "person:marin-kim",
    )
    ts = 0.0
    for left, right in planted:
        _observe_many(svc, left, 2 + rng.randint(0, 1), ts)
        ts += 1.0
        _observe_many(svc, right, 2 + rng.randint(0, 1), ts)
        ts += 1.0
    for attr in distractors:
        _observe_many(svc, attr, 2 + rng.randint(0, 2), ts)
        ts += 1.0
    truth = {frozenset(pair) for pair in planted}
    return svc, truth


def _pair_from_payload(payload: Dict) -> frozenset[str] | None:
    if "canonical_attr" in payload and "alias_attr" in payload:
        return frozenset((payload["canonical_attr"], payload["alias_attr"]))
    return None


def run_seed(seed: int, k: int = 20) -> Dict:
    svc, truth = _fixture(seed)
    rows = svc.list_suggestions(SITE, USER, now=100.0)[:k]
    predicted = {
        pair for pair in (_pair_from_payload(row["payload"]) for row in rows)
        if pair is not None
    }
    hits = len(predicted & truth)
    precision = hits / float(len(predicted) or 1)
    recall = hits / float(len(truth) or 1)
    return {
        "seed": seed,
        "precision": precision,
        "recall": recall,
        "suggestions": len(rows),
        "truth": len(truth),
    }


def _mean(values: Sequence[float]) -> float:
    return statistics.mean(values) if values else 0.0


def _sd(values: Sequence[float]) -> float:
    return statistics.pstdev(values) if len(values) > 1 else 0.0


def run(seeds: int = 6, k: int = 20, seed_offset: int = 0) -> Dict:
    rows = [run_seed(seed, k) for seed in range(seed_offset, seed_offset + seeds)]
    summary = {
        metric: {
            "mean": round(_mean([row[metric] for row in rows]), 6),
            "sd": round(_sd([row[metric] for row in rows]), 6),
        }
        for metric in ("precision", "recall", "suggestions")
    }
    return {
        "mode": "synthetic-canonicalization-eval",
        "schema_version": 1,
        "seeds": list(range(seed_offset, seed_offset + seeds)),
        "k": k,
        "summary": summary,
        "rows": rows,
    }


def format_report(report: Dict) -> str:
    lines = [
        "=" * 72,
        "SYNTHETIC CANONICALIZATION EVAL -- planted alias merges",
        f"seeds={len(report['seeds'])} k={report['k']}",
        "=" * 72,
        "metric       mean +/- sd",
        "------------ -------------",
    ]
    for metric in ("precision", "recall", "suggestions"):
        stats = report["summary"][metric]
        lines.append(f"{metric:<12} {stats['mean']:.3f} +/- {stats['sd']:.3f}")
    return "\n".join(lines)


def write_report(report: Dict, path: str | Path) -> Path:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return out


def main(argv: Sequence[str] | None = None) -> Dict:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seeds", type=int, default=6)
    parser.add_argument("--k", type=int, default=20)
    parser.add_argument("--seed-offset", type=int, default=0)
    parser.add_argument("--json", default="reports/canonicalization.json")
    args = parser.parse_args(argv)
    report = run(args.seeds, args.k, args.seed_offset)
    print(format_report(report))
    out = write_report(report, args.json)
    print(f"\nJSON report written to {out}")
    return report


if __name__ == "__main__":
    main()
