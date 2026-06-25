"""Resolution-derived decay.

This module is intentionally pure: no I/O, no storage, no LLM calls. It turns
existing edge metadata into a resolution score, then into a temperature that can
modulate decay when the feature flag is enabled.
"""
from __future__ import annotations

import math
from typing import Mapping

from .config import Config, DEFAULT


FACT_NAMESPACES = {"employer", "city", "role", "name", "origin", "timezone", "company"}
PROJECT_NAMESPACES = {"project", "deadline", "milestone"}
HABIT_NAMESPACES = {"habit", "cadence"}
STYLE_NAMESPACES = {"mood", "style"}
PREFERENCE_NAMESPACES = {"pref", "likes", "diet", "food"}


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def _namespace(attr: str) -> str:
    base = attr.lstrip("!")
    return base.split(":", 1)[0] if ":" in base else "attr"


def species_of(attr: str) -> str:
    """Map a namespaced attribute to coarse memory physics."""
    ns = _namespace(attr)
    if ns in FACT_NAMESPACES:
        return "fact"
    if ns in PROJECT_NAMESPACES:
        return "project"
    if ns in HABIT_NAMESPACES:
        return "habit"
    if ns in STYLE_NAMESPACES:
        return "style"
    if ns in PREFERENCE_NAMESPACES or attr.startswith("!"):
        return "preference"
    return "association"


def _ctx(ctx: Mapping | None, key: str, default=0.0):
    return (ctx or {}).get(key, default)


def _recency(edge, ctx: Mapping | None, cfg: Config) -> float:
    now = _ctx(ctx, "now", None)
    if now is None:
        return 0.0
    dt = max(0.0, float(now) - float(edge.last_reinforced))
    return math.exp(-cfg.lam * dt)


def resolution(attr: str, edge, ctx: Mapping | None = None,
               cfg: Config = DEFAULT) -> float:
    """Return v0 resolution in [0, 1] from fields already stored on Edge."""
    weights = []
    scores = []

    weights.append(cfg.res_w_explicit)
    scores.append(1.0 if edge.source in {"override", "stated"} else 0.0)

    weights.append(cfg.res_w_repeated)
    scores.append(1.0 if edge.hits >= cfg.res_repeat_hits else 0.0)

    weights.append(cfg.res_w_recent)
    scores.append(_recency(edge, ctx, cfg))

    total = sum(w for w in weights if w > 0)
    if total <= 0:
        return 0.0
    raw = sum(w * s for w, s in zip(weights, scores) if w > 0) / total
    if edge.source != "override":
        raw = min(raw, cfg.resolution_cap_non_override)
    return _clamp(raw, 0.0, 1.0)


def temperature(attr: str, edge, conflict: float = 0.0,
                cfg: Config = DEFAULT, ctx: Mapping | None = None) -> float:
    """Return decay temperature in [0, 1]. Overrides are handled by decay()."""
    res = resolution(attr, edge, ctx, cfg)
    heat = cfg.heat_gain * _clamp(float(conflict or 0.0), 0.0, 1.0)
    floor = cfg.temperature_floor_non_override if edge.source != "override" else 0.0
    return _clamp((1.0 - res) + heat, floor, 1.0)


def species_multiplier(attr: str, cfg: Config = DEFAULT) -> float:
    table = getattr(cfg, "species_decay", {}) or {}
    try:
        return float(table.get(species_of(attr), 1.0))
    except AttributeError:
        return 1.0


def lambda_eff(attr: str, edge, ctx: Mapping | None = None,
               conflict: float = 0.0, cfg: Config = DEFAULT) -> float:
    """Effective decay rate for one edge when resolution decay is enabled."""
    return cfg.lam * temperature(attr, edge, conflict, cfg, ctx) * species_multiplier(attr, cfg)


def phase(attr: str, edge, cfg: Config = DEFAULT,
          ctx: Mapping | None = None) -> str:
    """Human-readable phase for UI/debugging only."""
    if edge.source == "override":
        return "locked"
    res = resolution(attr, edge, ctx, cfg)
    if res >= cfg.phase_crystal:
        return "crystal"
    if res >= 0.5:
        return "liquid"
    return "vapor"
