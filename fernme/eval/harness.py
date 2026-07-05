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
METRICS = ("recall_at_k", "precision_at_k", "stale_recall_rate", "action_quality",
           "token_estimate", "llm_calls")
METHOD_ORDER = ("fern_pure", "fern_entities", "recency", "frequency", "bm25")
METHOD_LABELS = {
    "fern_pure": "FERNme pure",
    "fern_entities": "FERNme entities",
    "recency": "recency",
    "frequency": "frequency",
    "bm25": "BM25 Cabinet",
}
REGIME_ORDER = ("static", "abrupt_drift", "gradual_drift", "staleness",
                "contextual", "fragmented_entity", "outcome")


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
class ActionRound:
    ts: float
    options: Tuple[str, ...]
    correct_attr: str
    context: Tuple[str, ...] = ()


@dataclass(frozen=True)
class Scenario:
    name: str
    events: Tuple[HarnessEvent, ...]
    probes: Tuple[Probe, ...]
    cfg_overrides: Dict[str, float]
    setup_entities: Optional[Callable[[FernService], None]] = None
    action_rounds: Tuple[ActionRound, ...] = ()


@dataclass(frozen=True)
class MethodResult:
    method: str
    regime: str
    recall_at_k: float
    precision_at_k: float
    stale_recall_rate: float
    action_quality: float
    token_estimate: float
    llm_calls: float

    def as_dict(self) -> Dict[str, float | str]:
        return {
            "method": self.method,
            "regime": self.regime,
            "recall_at_k": self.recall_at_k,
            "precision_at_k": self.precision_at_k,
            "stale_recall_rate": self.stale_recall_rate,
            "action_quality": self.action_quality,
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


def _abrupt_drift_scenario(seed: int) -> Scenario:
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
        name="abrupt_drift",
        events=tuple(events),
        probes=(Probe(
            query="What should guide the current cafe recommendation after the taste shift?",
            context=("ctx:current-cafe",),
            relevant_attrs=new,
            stale_attrs=old,
        ),),
        cfg_overrides={"lam": 0.10, "floor": 0.5},
    )


def _gradual_drift_scenario(seed: int) -> Scenario:
    rng = random.Random(seed + 1500)
    persistent = (
        "pref:quiet-delivery",
        "pref:paper-receipts",
        "style:direct-updates",
        "food:vegetable-soup",
        "brand:harbor-market",
    )
    old_shift = ("pref:morning-slot", "drink:dark-roast", "pace:slow-browse")
    new_shift = ("pref:evening-slot", "drink:mint-tea", "pace:quick-pickup")
    distractors = ("topic:parking", "topic:coupon", "topic:window-display")
    events: List[HarnessEvent] = []
    for day in range(0, 128, 2):
        tags = list(rng.sample(persistent, 2))
        if day < 48:
            tags.append(rng.choice(old_shift))
        elif day < 72:
            tags.append(rng.choice((old_shift[0], new_shift[0])))
            tags.append(rng.choice(old_shift[1:]))
        elif day < 96:
            tags.append(rng.choice(new_shift[:2]))
            tags.append(rng.choice((old_shift[2], new_shift[2])))
        else:
            tags.append(rng.choice(new_shift))
        if rng.random() < 0.20:
            tags.append(rng.choice(distractors))
        events.append(_event(
            float(day),
            "visit",
            tags,
            "Fictional long-running account: five durable preferences persist while "
            "delivery time, drink, and pace shift gradually across the season.",
        ))
    return Scenario(
        name="gradual_drift",
        events=tuple(events),
        probes=(Probe(
            query="Which durable and current preferences should guide the account now?",
            context=("ctx:current-season",),
            relevant_attrs=persistent + new_shift,
            stale_attrs=old_shift,
        ),),
        cfg_overrides={"lam": 0.06, "floor": 0.5},
    )


def _staleness_scenario(seed: int) -> Scenario:
    rng = random.Random(seed + 1700)
    fast_old = ("fast:desk-snacks", "fast:weekday-courier")
    fast_new = ("fast:no-snacks", "fast:locker-pickup")
    slow_old = ("slow:solo-planner", "slow:harbor-loft")
    slow_new = ("slow:team-coordinator", "slow:garden-studio")
    stable = ("pref:plain-language", "pref:email-summary", "topic:budget-ceiling")
    events: List[HarnessEvent] = []
    for day in range(0, 85, 5):
        events.append(_event(
            float(day),
            "checkin",
            list(rng.sample(stable, 2)) + [rng.choice(fast_old), rng.choice(slow_old)],
            "Early fictional profile state: old fast habits and old slow identity facts.",
        ))
    for day in range(120, 220, 10):
        events.append(_event(
            float(day),
            "checkin",
            list(rng.sample(stable, 2)) + [rng.choice(fast_new)],
            "Middle period: fast-changing preferences have moved to the new state.",
        ))
    for day in range(280, 380, 10):
        events.append(_event(
            float(day),
            "checkin",
            list(rng.sample(stable, 2)) + [rng.choice(fast_new), rng.choice(slow_new)],
            "Late fictional profile state: slow-changing facts are now updated too.",
        ))
    return Scenario(
        name="staleness",
        events=tuple(events),
        probes=(Probe(
            query="Which current facts are safe to act on at the long-timescale probe?",
            context=("ctx:long-timescale",),
            relevant_attrs=stable + fast_new + slow_new,
            stale_attrs=fast_old + slow_old,
        ),),
        cfg_overrides={"lam": 0.04, "floor": 0.5},
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


def _fragmented_entity_scenario(seed: int) -> Scenario:
    rng = random.Random(seed + 2500)
    aliases = (
        "person:leona",
        "person:leona-park",
        "person:l-park",
        "person:lp",
        "person:leona-p",
        "person:dr-park",
        "person:mentor-leona",
    )
    distractors = (
        "topic:quarterly-plan",
        "project:cedar-demo",
        "org:bluebird-labs",
        "topic:launch-budget",
        "person:marin-kim",
        "topic:board-update",
    )
    events: List[HarnessEvent] = []
    ts = 0.0
    for alias in aliases:
        events.append(_event(
            ts,
            "note",
            [alias],
            "Fictional fragmented profile mention for Leona Park under a weak alias.",
        ))
        ts += 1.0
    for attr in distractors:
        for _ in range(3 + rng.randint(0, 1)):
            events.append(_event(
                ts,
                "note",
                [attr],
                "Strong fictional distractor signal around projects, budget, and board updates.",
            ))
            ts += 1.0
    rng.shuffle(events)
    ordered = tuple(_event(i, ev.kind, ev.tags, ev.text) for i, ev in enumerate(events))

    def setup_entities(svc: FernService) -> None:
        leona = svc.entity_create(SITE, USER, "person", "Leona Park")
        project = svc.entity_create(SITE, USER, "project", "Cedar demo")
        for alias in aliases:
            svc.entity_link_alias(SITE, USER, leona, alias)
        svc.entity_link_alias(SITE, USER, project, "project:cedar-demo")
        svc.entity_relate(SITE, USER, leona, "works_on", project, ts=40.0)

    return Scenario(
        name="fragmented_entity",
        events=ordered,
        probes=(Probe(
            query="Find the fragmented person signal for Leona Park.",
            context=aliases[:2],
            relevant_attrs=("entity:Leona Park",),
        ),),
        cfg_overrides={},
        setup_entities=setup_entities,
    )


def _outcome_scenario(seed: int) -> Scenario:
    rng = random.Random(seed + 3000)
    options = (
        "option:atrium-seat",
        "option:courtyard-table",
        "option:quiet-suite",
        "option:counter-service",
    )
    events: List[HarnessEvent] = []
    for i, option in enumerate(options):
        events.append(_event(
            float(i),
            "option",
            [option],
            "Fictional booking option shown before the goal-loop starts.",
        ))
    rounds: List[ActionRound] = []
    for i in range(14):
        correct = "option:courtyard-table" if i < 7 else "option:quiet-suite"
        shuffled = list(options)
        rng.shuffle(shuffled)
        rounds.append(ActionRound(
            ts=10.0 + i,
            options=tuple(shuffled),
            correct_attr=correct,
            context=("ctx:booking-goal",),
        ))
    return Scenario(
        name="outcome",
        events=tuple(events),
        probes=(Probe(
            query="Which option should the agent pick for the booking goal?",
            context=("ctx:booking-goal",),
            relevant_attrs=("option:courtyard-table", "option:quiet-suite"),
        ),),
        cfg_overrides={},
        action_rounds=tuple(rounds),
    )


def build_scenarios(seed: int) -> Tuple[Scenario, ...]:
    """Return deterministic synthetic scenarios with hidden answer keys."""
    return (
        _static_scenario(seed),
        _abrupt_drift_scenario(seed),
        _gradual_drift_scenario(seed),
        _staleness_scenario(seed),
        _contextual_scenario(seed),
        _fragmented_entity_scenario(seed),
        _outcome_scenario(seed),
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
    if scenario.cfg_overrides:
        svc.decay(SITE, USER, now=now)
    card = svc.card(SITE, USER, context=list(probe.context), now=now)
    pred = []
    for link in card["links"][:k]:
        if use_entities and scenario.name == "fragmented_entity" and link.get("entity"):
            pred.append(f"entity:{link['entity']}")
        else:
            pred.append(link["attr"])
    return pred, int(card["tokens"]), svc.llm_calls


def _choose_from_scores(options: Sequence[str], scores: Dict[str, float]) -> str:
    return sorted(options, key=lambda attr: (-scores.get(attr, 0.0), attr))[0]


def _predict_fern_outcome(
    scenario: Scenario,
    cfg: Config,
    use_entities: bool,
    k: int,
) -> Tuple[float, int, int]:
    method_cfg = replace(cfg, entities=use_entities, entity_aggregation=use_entities)
    svc = FernService(":memory:", cfg=method_cfg)
    svc.track_style = False
    svc.consent(SITE, USER, True)
    for ev in scenario.events:
        svc.observe(SITE, USER, ev.kind, {"tags": list(ev.tags), "text": ev.text}, ts=ev.ts)
    successes = 0
    tokens: List[int] = []
    for round_ in scenario.action_rounds:
        card = svc.card(SITE, USER, context=list(round_.context), now=round_.ts)
        tokens.append(int(card["tokens"]))
        scores = {
            link["attr"]: (k - idx)
            for idx, link in enumerate(card["links"][:k])
        }
        pick = _choose_from_scores(round_.options, scores)
        success = pick == round_.correct_attr
        successes += int(success)
        svc.record_outcome(SITE, USER, success, attrs=[pick], now=round_.ts, weight=1.0)
    return successes / float(len(scenario.action_rounds) or 1), int(_mean(tokens)), svc.llm_calls


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


def _predict_baseline_outcome(
    method: str,
    scenario: Scenario,
    probe: Probe,
    k: int,
) -> Tuple[float, int, int]:
    if method == "recency":
        pred, tokens, calls = _predict_recency(scenario, k)
    elif method == "frequency":
        pred, tokens, calls = _predict_frequency(scenario, k)
    elif method == "bm25":
        pred, tokens, calls = _predict_bm25(scenario, probe, k)
    else:
        raise ValueError(f"unknown outcome baseline {method}")
    scores = {attr: (k - idx) for idx, attr in enumerate(pred[:k])}
    successes = 0
    for round_ in scenario.action_rounds:
        pick = _choose_from_scores(round_.options, scores)
        successes += int(pick == round_.correct_attr)
    return successes / float(len(scenario.action_rounds) or 1), tokens, calls


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
    precision = hits / float(k)
    return MethodResult(
        method=method,
        regime=regime,
        recall_at_k=hits / float(len(relevant) or 1),
        precision_at_k=precision,
        stale_recall_rate=stale_hits / float(len(stale) or 1),
        action_quality=precision,
        token_estimate=float(token_estimate),
        llm_calls=float(llm_calls),
    )


def _score_outcome(method: str, scenario: Scenario, probe: Probe, cfg: Config,
                   k: int) -> MethodResult:
    if method == "fern_pure":
        quality, tokens, calls = _predict_fern_outcome(scenario, cfg, False, k)
    elif method == "fern_entities":
        quality, tokens, calls = _predict_fern_outcome(scenario, cfg, True, k)
    else:
        quality, tokens, calls = _predict_baseline_outcome(method, scenario, probe, k)
    return MethodResult(
        method=method,
        regime=scenario.name,
        recall_at_k=quality,
        precision_at_k=quality,
        stale_recall_rate=0.0,
        action_quality=quality,
        token_estimate=float(tokens),
        llm_calls=float(calls),
    )


def _run_method(method: str, scenario: Scenario, probe: Probe, cfg: Config,
                k: int) -> MethodResult:
    if scenario.action_rounds:
        return _score_outcome(method, scenario, probe, cfg, k)
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
        lines.append("method          recall@k        precision@k     stale-rate      action          tokens          llm")
        lines.append("--------------- --------------- --------------- --------------- --------------- --------------- ------")
        for method in METHOD_ORDER:
            stats = report["summary"][regime][method]
            lines.append(
                f"{METHOD_LABELS[method]:<15} "
                f"{_fmt_metric(stats['recall_at_k']):<15} "
                f"{_fmt_metric(stats['precision_at_k']):<15} "
                f"{_fmt_metric(stats['stale_recall_rate']):<15} "
                f"{_fmt_metric(stats['action_quality']):<15} "
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
