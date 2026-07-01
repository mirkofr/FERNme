"""Hebbian write rule (no LLM) + ACT-R decay. Pure arithmetic on the graph."""
from __future__ import annotations
import math
from typing import Dict, List, Tuple
from ..core.graph import UserGraph, AssocGraph, Event, Edge
from ..config import Config, DEFAULT
from .. import resolution as _resolution
from ..identity import is_permanent_attr


def _saturating_bump(w: float, rate: float, mag: float, w_max: float) -> float:
    # w <- w + rate*mag*(1 - w/w_max): fast early, asymptotes to w_max, never exceeds it
    return w + rate * mag * (1.0 - w / w_max)


def observe(ug: UserGraph, assoc: AssocGraph, event: Event,
            mapped: List[Tuple[str, float]], cfg: Config = DEFAULT,
            salience=None, provenance: str = "inferred") -> None:
    """Apply one event to the user graph + shared association graph.
    Crucially: this function calls no LLM and does no vector search."""
    active = mapped
    incoming_provenance = "stated" if provenance in {"stated", "override"} else "inferred"
    # 1) strengthen user -> attr
    for attr, mag in active:
        e = ug.edges.get(attr)
        if e is None:
            e = Edge(weight=0.0, source="known", last_reinforced=event.ts,
                     provenance=incoming_provenance)
            ug.edges[attr] = e
        elif e.source == "guessed":
            e.weight = 0.0; e.hits = 0; e.fast = 0.0   # shed borrowed prior
        if incoming_provenance == "stated":
            e.provenance = "stated"
        e.weight = _saturating_bump(e.weight, cfg.alpha, mag, cfg.w_max)
        e.fast = _saturating_bump(e.fast, cfg.alpha_fast, mag, cfg.w_max)
        e.hits += 1
        e.confidence = 1.0 - math.exp(-cfg.gamma * e.hits)
        e.source = "known" if e.source != "override" else "override"
        e.last_reinforced = event.ts
        s_in = (salience or {}).get(attr, 0.0)
        if attr.startswith("!"):
            s_in = max(s_in, cfg.salience_neg)
        if s_in > e.salience:
            e.salience = min(1.0, s_in)
        ug.history.setdefault(attr, []).append(event.ts)

    # 2) strengthen attr <-> attr (Hebb: fire together, wire together)
    for i in range(len(active)):
        for j in range(i + 1, len(active)):
            a, ma = active[i]
            b, mb = active[j]
            assoc.set_edge(a, b, _saturating_bump(assoc.get(a, b),
                                                  cfg.beta, ma * mb, cfg.w_max))


def decay(ug: UserGraph, now: float, cfg: Config = DEFAULT,
          conflict_map: Dict[str, float] = None, ctx: Dict = None) -> int:
    """Batch job: fade edges not reinforced; drop below floor. Overrides never
    decay. Returns number of edges dropped. Forgetting is a feature: it keeps the
    card small and cheap regardless of tenure."""
    dropped = []
    for attr, e in ug.edges.items():
        if e.source == "override":
            continue
        sticky_permanent = (
            cfg.identity_sticky
            and e.source != "superseded"
            and is_permanent_attr(attr)
        )
        dt = max(0.0, now - e.last_reinforced)
        if cfg.resolution:
            edge_ctx = dict(ctx or {})
            edge_ctx.setdefault("now", now)
            lam_eff = _resolution.lambda_eff(
                attr, e, edge_ctx, (conflict_map or {}).get(attr, 0.0), cfg)
        else:
            lam_eff = cfg.lam * (1.0 - cfg.salience_beta * e.salience)
        e.weight = e.weight * math.exp(-lam_eff * dt)
        e.salience = e.salience * math.exp(-cfg.lam * cfg.salience_decay * dt)
        e.fast = e.fast * math.exp(-cfg.lam_fast * dt)   # fast lane fades much quicker
        if sticky_permanent:
            e.weight = max(e.weight, cfg.floor)
        e.last_reinforced = now            # reset clock -> safe to call periodically
        if e.weight < cfg.floor:
            dropped.append(attr)
    for attr in dropped:
        del ug.edges[attr]
        ug.history.pop(attr, None)
    return len(dropped)
