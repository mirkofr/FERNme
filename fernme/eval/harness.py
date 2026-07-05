"""Synthetic multi-regime eval harness with deterministic baselines.

Run:
    python -m fernme.eval.harness --seeds 6 --json reports/eval_harness.json
"""
from __future__ import annotations

import argparse
import json
import math
import random
import re
import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Tuple

from ..config import Config, DEFAULT
from ..retrieve.card import estimate_tokens
from ..service import FernService

SITE = "harness.example"
USER = "fictional-user"
METRICS = ("recall_at_k", "precision_at_k", "stale_recall_rate",
           "token_estimate", "llm_calls")
METHOD_ORDER = ("fern_pure", "fern_entities", "recency", "frequency", "bm25")
METHOD_LABELS = {
    "fern_pure": "FERNme pure",
    "fern_entities": "FERNme entities",
    "recency": "recency",
    "frequency": "frequency",
    "bm25": "BM25 Cabinet",
}
REGIME_ORDER = ("static", "drift", "contextual")


@dataclass(frozen=True)
class HarnessEvent:
    ts: float
    kind: str
    tags: Tuple[str, ...]
    text: str


@dataclass(frozen=True)
class Probe:
    query: str
    context: Tuple[str, ...]
    relevant_attrs: Tuple[str, ...]
    stale_attrs: Tuple[str, ...] = ()


@dataclass(frozen=True)
class Scenario:
    name: str
    events: Tuple[HarnessEvent, ...]
    probes: Tuple[Probe, ...]
    cfg_overrides: Dict[str, float]
    setup_entities: Optional[Callable[[FernService], None]] = None


@dataclass(frozen=True)
class MethodResult:
    method: str
    regime: str
    recall_at_k: float
    precision_at_k: float
    stale_recall_rate: float
    token_estimate: float
    llm_calls: float

    def as_dict(self) -> Dict[str, float | str]:
        return {
            "method": self.method,
            "regime": self.regime,
            "recall_at_k": self.recall_at_k,
            "precision_at_k": self.precision_at_k,
            "stale_recall_rate": self.stale_recall_rate,
            "token_estimate": self.token_estimate,
            "llm_calls": self.llm_calls,
        }


def _scenario_cfg(base: Config, overrides: Dict[str, float]) -> Config:
    return replace(base, **overrides) if overrides else base


def _event(ts: float, kind: str, tags: Sequence[str], text: str) -> HarnessEvent:
    return HarnessEvent(float(ts), kind, tuple(tags), text)


def _static_scenario(seed: int) -> Scenario:
    rng = random.Random(seed)
    core = (
        "pref:jasmine-tea",
        "pref:linen-shirts",
        "style:minimal",
        "size:medium",
        "person:noah",
        "person:noah-k",
        "project:atlas-demo",
    )
    distractors = (
        "pref:espresso",
        "pref:wool-coat",
        "style:maximal",
        "size:large",
        "food:blueberry-tart",
        "topic:gift-wrap",
    )
    events: List[HarnessEvent] = []
    ts = 0.0
    for _ in range(22):
        tags = rng.sample(core[:4], 2)
        if rng.random() < 0.45:
            tags.append(rng.choice(core[4:]))
        events.append(_event(
            ts,
            "purchase",
            tags,
            "Fictional atelier visit: jasmine tea, linen shirts, minimal styling, "
            "medium sizing, and Noah's Atlas demo came up.",
        ))
        ts += 1.0
    for _ in range(8):
        tags = rng.sample(distractors, 2)
        events.append(_event(
            ts,
            "browse",
            tags,
            "Low-signal browsing around espresso, wool coats, gift wrap, and tart options.",
        ))
        ts += 1.0
    rng.shuffle(events)
    ordered = tuple(_event(i, ev.kind, ev.tags, ev.text) for i, ev in enumerate(events))

    def setup_entities(svc: FernService) -> None:
        noah = svc.entity_create(SITE, USER, "person", "Noah Kim")
        project = svc.entity_create(SITE, USER, "project", "Atlas demo")
        svc.entity_link_alias(SITE, USER, noah, "person:noah")
        svc.entity_link_alias(SITE, USER, noah, "person:noah-k")
        svc.entity_link_alias(SITE, USER, project, "project:atlas-demo")
        svc.entity_relate(SITE, USER, noah, "works_on", project, ts=40.0)

    return Scenario(
        name="static",
        events=ordered,
        probes=(Probe(
            query="Which durable preferences should guide an atelier recommendation?",
            context=("ctx:atelier", "person:noah"),
            relevant_attrs=core[:4],
        ),),
        cfg_overrides={},
        setup_entities=setup_entities,
    )


def _drift_scenario(seed: int) -> Scenario:
    rng = random.Random(seed + 1000)
    old = (
        "pref:dark-roast",
        "food:cinnamon-roll",
        "style:slow-browse",
        "brand:maple-home",
    )
    new = (
        "pref:mint-tea",
        "food:rice-bowl",
        "style:quick-pickup",
        "brand:river-studio",
    )
    neutral = ("topic:receipt", "topic:window-display", "topic:parking")
    events: List[HarnessEvent] = []
    ts = 0.0
    for _ in range(48):
        tags = list(rng.sample(old, 2))
        if rng.random() < 0.25:
            tags.append(rng.choice(neutral))
        events.append(_event(
            ts,
            "purchase",
            tags,
            "Earlier fictional cafe visits favored dark roast, cinnamon rolls, "
            "slow browsing, and Maple Home.",
        ))
        ts += 1.0
    for _ in range(24):
        tags = list(rng.sample(new, 2))
        if rng.random() < 0.25:
            tags.append(rng.choice(neutral))
        events.append(_event(
            ts,
            "purchase",
            tags,
            "Recent fictional cafe visits favor mint tea, rice bowls, quick pickup, "
            "and River Studio.",
        ))
        ts += 1.0
    return Scenario(
        name="drift",
        events=tuple(events),
        probes=(Probe(
            query="What should guide the current cafe recommendation after the taste shift?",
            context=("ctx:current-cafe",),
            relevant_attrs=new,
            stale_attrs=old,
        ),),
        cfg_overrides={"lam": 0.10, "floor": 0.5},
    )


def _contextual_scenario(seed: int) -> Scenario:
    rng = random.Random(seed + 2000)
    lunch = (
        "pref:quiet-booth",
        "food:tomato-soup",
        "drink:sparkling-water",
        "pace:unhurried",
    )
    morning = (
        "pref:window-seat",
        "food:granola",
        "drink:iced-coffee",
        "pace:quick-stop",
    )
    events: List[HarnessEvent] = []
    ts = 0.0
    for _ in range(34):
        lunch_tags = ["ctx:lunch"] + rng.sample(lunch, 2)
        events.append(_event(
            ts,
            "visit",
            lunch_tags,
            "Fictional lunch visits mention a quiet booth, tomato soup, sparkling "
            "water, and an unhurried pace.",
        ))
        ts += 1.0
        morning_tags = ["ctx:morning"] + rng.sample(morning, 2)
        events.append(_event(
            ts,
            "visit",
            morning_tags,
            "Fictional morning visits mention window seats, granola, iced coffee, "
            "and a quick stop.",
        ))
        ts += 1.0
    return Scenario(
        name="contextual",
        events=tuple(events),
        probes=(Probe(
            query="For lunch today, which facts are relevant?",
            context=("ctx:lunch",),
            relevant_attrs=lunch,
        ),),
        cfg_overrides={},
    )


def build_scenarios(seed: int) -> Tuple[Scenario, ...]:
    """Return deterministic synthetic scenarios with hidden answer keys."""
    return (
        _static_scenario(seed),
        _drift_scenario(seed),
        _contextual_scenario(seed),
    )


def _predict_fern(
    scenario: Scenario,
    probe: Probe,
    cfg: Config,
    use_entities: bool,
    k: int,
) -> Tuple[List[str], int, int]:
    method_cfg = replace(cfg, entities=use_entities, entity_aggregation=use_entities)
    svc = FernService(":memory:", cfg=method_cfg)
    svc.track_style = False
    svc.consent(SITE, USER, True)
    for ev in scenario.events:
        svc.observe(SITE, USER, ev.kind, {"tags": list(ev.tags), "text": ev.text}, ts=ev.ts)
        if scenario.cfg_overrides:
            svc.decay(SITE, USER, now=ev.ts)
    if scenario.setup_entities:
        scenario.setup_entities(svc)
    now = scenario.events[-1].ts + 1.0 if scenario.events else 0.0
    card = svc.card(SITE, USER, context=list(probe.context), now=now)
    return [link["attr"] for link in card["links"][:k]], int(card["tokens"]), svc.llm_calls


def _event_tags(events: Iterable[HarnessEvent]) -> List[Tuple[float, Tuple[str, ...]]]:
    return [(ev.ts, ev.tags) for ev in events]


def _predict_recency(scenario: Scenario, k: int) -> Tuple[List[str], int, int]:
    seen: Dict[str, float] = {}
    for ts, tags in _event_tags(scenario.events):
        for tag in tags:
            if not tag.startswith("ctx:"):
                seen[tag] = ts
    pred = [attr for attr, _ in sorted(seen.items(), key=lambda item: (-item[1], item[0]))[:k]]
    return pred, _attr_token_estimate(pred), 0


def _predict_frequency(scenario: Scenario, k: int) -> Tuple[List[str], int, int]:
    counts: Counter[str] = Counter()
    for _ts, tags in _event_tags(scenario.events):
        counts.update(tag for tag in tags if not tag.startswith("ctx:"))
    pred = [attr for attr, _ in sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:k]]
    return pred, _attr_token_estimate(pred), 0


_TOKEN_RE = re.compile(r"[a-z0-9:_-]+")


def _terms(text: str) -> List[str]:
    return _TOKEN_RE.findall(text.lower())


def _predict_bm25(scenario: Scenario, probe: Probe, k: int) -> Tuple[List[str], int, int]:
    docs = []
    for ev in scenario.events:
        text = " ".join((ev.text, " ".join(ev.tags)))
        terms = _terms(text)
        docs.append({"terms": terms, "tags": ev.tags, "text": ev.text})
    if not docs:
        return [], 0, 0
    df: Counter[str] = Counter()
    for doc in docs:
        df.update(set(doc["terms"]))
    avgdl = sum(len(doc["terms"]) for doc in docs) / float(len(docs))
    query_terms = _terms(" ".join((probe.query, " ".join(probe.context))))
    qtf = Counter(query_terms)
    scored = []
    for idx, doc in enumerate(docs):
        tf = Counter(doc["terms"])
        dl = len(doc["terms"]) or 1
        score = 0.0
        for term, q_count in qtf.items():
            if term not in tf:
                continue
            idf = math.log(1.0 + (len(docs) - df[term] + 0.5) / (df[term] + 0.5))
            denom = tf[term] + 1.5 * (1.0 - 0.75 + 0.75 * dl / max(avgdl, 1e-9))
            score += q_count * idf * (tf[term] * 2.5) / denom
        scored.append((score, idx, doc))
    scored.sort(key=lambda item: (-item[0], item[1]))
    attrs: List[str] = []
    used_text: List[str] = []
    for score, _idx, doc in scored:
        if score <= 0 and attrs:
            break
        used_text.append(doc["text"])
        for tag in doc["tags"]:
            if tag.startswith("ctx:") or tag in attrs:
                continue
            attrs.append(tag)
            if len(attrs) >= k:
                return attrs, estimate_tokens(" ".join(used_text)), 0
    return attrs[:k], estimate_tokens(" ".join(used_text)), 0


def _attr_token_estimate(attrs: Sequence[str]) -> int:
    wire = "user:baseline | " + " ".join(f"{attr}:1*" for attr in attrs)
    return estimate_tokens(wire)


def _score_prediction(
    method: str,
    regime: str,
    pred: Sequence[str],
    token_estimate: int,
    llm_calls: int,
    probe: Probe,
    k: int,
) -> MethodResult:
    top = list(pred[:k])
    relevant = set(probe.relevant_attrs)
    stale = set(probe.stale_attrs)
    hits = len(set(top) & relevant)
    stale_hits = len(set(top) & stale)
    return MethodResult(
        method=method,
        regime=regime,
        recall_at_k=hits / float(len(relevant) or 1),
        precision_at_k=hits / float(k),
        stale_recall_rate=stale_hits / float(len(stale) or 1),
        token_estimate=float(token_estimate),
        llm_calls=float(llm_calls),
    )


def _run_method(method: str, scenario: Scenario, probe: Probe, cfg: Config,
                k: int) -> MethodResult:
    if method == "fern_pure":
        pred, tokens, calls = _predict_fern(scenario, probe, cfg, False, k)
    elif method == "fern_entities":
        pred, tokens, calls = _predict_fern(scenario, probe, cfg, True, k)
    elif method == "recency":
        pred, tokens, calls = _predict_recency(scenario, k)
    elif method == "frequency":
        pred, tokens, calls = _predict_frequency(scenario, k)
    elif method == "bm25":
        pred, tokens, calls = _predict_bm25(scenario, probe, k)
    else:
        raise ValueError(f"unknown method {method}")
    return _score_prediction(method, scenario.name, pred, tokens, calls, probe, k)


def _mean(values: Sequence[float]) -> float:
    return statistics.mean(values) if values else 0.0


def _sd(values: Sequence[float]) -> float:
    return statistics.pstdev(values) if len(values) > 1 else 0.0


def summarize(rows: Sequence[Dict]) -> Dict[str, Dict[str, Dict[str, Dict[str, float]]]]:
    grouped: Dict[str, Dict[str, Dict[str, List[float]]]] = defaultdict(
        lambda: defaultdict(lambda: defaultdict(list)))
    for row in rows:
        for metric in METRICS:
            grouped[row["regime"]][row["method"]][metric].append(float(row[metric]))
    out: Dict[str, Dict[str, Dict[str, Dict[str, float]]]] = {}
    for regime in REGIME_ORDER:
        out[regime] = {}
        for method in METHOD_ORDER:
            metrics = grouped[regime][method]
            out[regime][method] = {
                metric: {
                    "mean": round(_mean(metrics[metric]), 6),
                    "sd": round(_sd(metrics[metric]), 6),
                }
                for metric in METRICS
            }
    return out


def run(
    seeds: int = 6,
    cfg: Config = DEFAULT,
    k: int = 5,
    seed_offset: int = 0,
) -> Dict:
    """Run the harness.

    `cfg` is the control Config used by FERNme pure. The entity method derives from
    the same Config with `entities=True` and `entity_aggregation=True`, so future
    flags can be evaluated by passing a different Config into this function.
    """
    rows: List[Dict] = []
    for seed in range(seed_offset, seed_offset + seeds):
        for scenario in build_scenarios(seed):
            method_cfg = _scenario_cfg(cfg, scenario.cfg_overrides)
            for probe in scenario.probes:
                for method in METHOD_ORDER:
                    result = _run_method(method, scenario, probe, method_cfg, k)
                    rows.append({"seed": seed, **result.as_dict()})
    return {
        "mode": "synthetic-eval-harness",
        "schema_version": 1,
        "seeds": list(range(seed_offset, seed_offset + seeds)),
        "k": k,
        "methods": list(METHOD_ORDER),
        "regimes": list(REGIME_ORDER),
        "metrics": list(METRICS),
        "summary": summarize(rows),
        "rows": rows,
    }


def _fmt_metric(stats: Dict[str, float], places: int = 3) -> str:
    return f"{stats['mean']:.{places}f} +/- {stats['sd']:.{places}f}"


def format_tables(report: Dict) -> str:
    lines = []
    lines.append("=" * 86)
    lines.append("SYNTHETIC EVAL HARNESS -- hidden answer keys; no real-user data")
    lines.append(f"seeds={len(report['seeds'])} k={report['k']} methods={', '.join(report['methods'])}")
    lines.append("=" * 86)
    for regime in REGIME_ORDER:
        lines.append("")
        lines.append(regime.upper())
        lines.append("method          recall@k        precision@k     stale-rate      tokens          llm")
        lines.append("--------------- --------------- --------------- --------------- --------------- ------")
        for method in METHOD_ORDER:
            stats = report["summary"][regime][method]
            lines.append(
                f"{METHOD_LABELS[method]:<15} "
                f"{_fmt_metric(stats['recall_at_k']):<15} "
                f"{_fmt_metric(stats['precision_at_k']):<15} "
                f"{_fmt_metric(stats['stale_recall_rate']):<15} "
                f"{_fmt_metric(stats['token_estimate'], 1):<15} "
                f"{stats['llm_calls']['mean']:.0f}"
            )
    return "\n".join(lines)


def write_report(report: Dict, path: str | Path) -> Path:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return out


def main(argv: Optional[Sequence[str]] = None) -> Dict:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seeds", type=int, default=6)
    parser.add_argument("--k", type=int, default=5)
    parser.add_argument("--seed-offset", type=int, default=0)
    parser.add_argument("--json", default="reports/eval_harness.json",
                        help="Path to write the JSON report.")
    args = parser.parse_args(argv)
    report = run(seeds=args.seeds, k=args.k, seed_offset=args.seed_offset)
    print(format_tables(report))
    out = write_report(report, args.json)
    print(f"\nJSON report written to {out}")
    return report


if __name__ == "__main__":
    main()
