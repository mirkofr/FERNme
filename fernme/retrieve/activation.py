"""Spreading activation retrieval (Collins & Loftus + ACT-R). No per-turn
vector search: relevance is found by activation flowing over the graph."""
from __future__ import annotations
import math
from typing import Dict, List
from ..core.graph import UserGraph, AssocGraph
from ..config import Config, DEFAULT


def base_level(ug: UserGraph, attr: str, now: float, cfg: Config = DEFAULT) -> float:
    """ACT-R base-level: recency x frequency. B = ln(sum (now - t + 1)^-d)."""
    ts = ug.history.get(attr, [])
    if not ts:
        e = ug.edges.get(attr)
        return (e.weight / cfg.w_max) if e else 0.0
    s = sum((max(now - t, 0.0) + 1.0) ** (-cfg.bl_decay) for t in ts)
    return math.log(s) if s > 0 else 0.0


def spread(ug: UserGraph, assoc: AssocGraph, seeds: List[str], now: float,
           cfg: Config = DEFAULT) -> Dict[str, float]:
    """Activate user node + seed attrs, flow over weighted assoc edges for
    cfg.hops, attenuating with distance, then apply lateral inhibition within
    mutually-exclusive clusters (attr prefix before ':')."""
    act: Dict[str, float] = {}
    # initial activation = base-level for every stored attr; seeds get a boost
    for attr in ug.edges:
        act[attr] = base_level(ug, attr, now, cfg)
    for s in seeds:
        act[s] = act.get(s, 0.0) + 1.0

    # spreading: A_i += sum_j A_j * w_ji / sum_k w_jk
    frontier = list(act.keys())
    for _ in range(cfg.hops):
        delta: Dict[str, float] = {}
        for j in frontier:
            nbrs = assoc.neighbors(j)
            tot = sum(w for _, w in nbrs)
            if tot <= 0:
                continue
            aj = act.get(j, 0.0)
            for nb, w in nbrs:
                delta[nb] = delta.get(nb, 0.0) + aj * (w / tot)
        for k, v in delta.items():
            act[k] = act.get(k, 0.0) + 0.5 * v   # 0.5 = inter-hop attenuation
        frontier = list(delta.keys())

    # lateral inhibition within clusters (e.g. size:S / size:M / size:L)
    clusters: Dict[str, List[str]] = {}
    for attr in act:
        if ":" in attr:
            clusters.setdefault(attr.split(":", 1)[0], []).append(attr)
    for members in clusters.values():
        if len(members) < 2:
            continue
        winner = max(members, key=lambda a: act[a])
        for a in members:
            if a != winner:
                act[a] *= 0.3
    return act


def ranked_attrs(ug, assoc, seeds, now, cfg=DEFAULT, k=5):
    """Rank the user's OWN attributes by spreading activation (recency x frequency
    + context spread). This is FERN's real retrieval path -- recency-aware, unlike
    a raw frequency count."""
    act = spread(ug, assoc, seeds, now, cfg)
    real = [(a, act.get(a, 0.0)) for a, e in ug.edges.items() if e.source != "guessed"]
    real.sort(key=lambda x: -x[1])
    return [a for a, _ in real[:k]]
