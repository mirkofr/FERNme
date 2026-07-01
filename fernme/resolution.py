"""Resolution-derived decay and volatility reliability.

This module is intentionally pure: no I/O, no storage, no LLM calls. It turns
existing edge metadata into a resolution score, then into a temperature that can
modulate decay when the feature flag is enabled.

Volatility is orthogonal to semantic categories: it describes how quickly a
kind of fact tends to go stale. A high-conflict edge verifies immediately,
because contradiction is an uncertainty signal before action. Age-only verify is
off by default because synthetic R3 evaluation showed it cannot separate silent
staleness from old-but-true facts well enough yet. Provenance is currently an
in-memory Edge field only; rows loaded from existing stores default to inferred
until Option B adds a storage migration.
"""
from __future__ import annotations

import math
from typing import Mapping

from .config import Config, DEFAULT
from . import curation as _curation


PERMANENT_NAMESPACES = {
    "name", "birthday", "origin", "nationality", "lang", "allergy",
    "health", "milestone", "event",
}
SLOW_NAMESPACES = {
    "employer", "company", "city", "role", "position", "affiliation",
    "status", "domain", "timezone",
}
PREFERENCE_NAMESPACES = {"pref", "likes", "diet", "food", "value", "goal"}
HABIT_NAMESPACES = {"habit", "cadence", "activity", "tool"}
VOLATILE_NAMESPACES = {"project", "deadline", "context", "traveling"}
STYLE_NAMESPACES = {"mood", "style"}


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def _namespace(attr: str) -> str:
    base = attr.lstrip("!")
    return base.split(":", 1)[0] if ":" in base else base


def species_of(attr: str) -> str:
    """Map a namespaced attribute to volatility class."""
    ns = _namespace(attr)
    if ns in PERMANENT_NAMESPACES:
        return "permanent"
    if ns in SLOW_NAMESPACES:
        return "slow"
    if ns in PREFERENCE_NAMESPACES or attr.startswith("!"):
        return "preference"
    if ns in HABIT_NAMESPACES:
        return "habit"
    if ns in VOLATILE_NAMESPACES or ns.startswith("current_"):
        return "volatile"
    if ns in STYLE_NAMESPACES:
        return "style"
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
    explicit = (
        edge.source in {"override", "stated"}
        or getattr(edge, "provenance", "inferred") == "stated"
    )
    scores.append(1.0 if explicit else 0.0)

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
    species = species_of(attr)
    half_lives = getattr(cfg, "volatility_half_lives", {}) or {}
    if species in half_lives:
        return (math.log(2.0) / max(float(cfg.lam), 1e-12)
                / max(float(half_lives[species]), 1e-12))
    table = getattr(cfg, "species_decay", {}) or {}
    try:
        return float(table.get(species, 1.0))
    except AttributeError:
        return 1.0


def half_life_days(attr: str, cfg: Config = DEFAULT) -> float:
    """Return the target half-life in days for an attr's volatility class."""
    species = species_of(attr)
    table = getattr(cfg, "volatility_half_lives", {}) or {}
    if species in table:
        return max(float(table[species]), 1e-12)
    mult = max(species_multiplier(attr, cfg), 1e-12)
    return math.log(2.0) / max(float(cfg.lam) * mult, 1e-12)


def volatility_lambda(attr: str, cfg: Config = DEFAULT) -> float:
    """Decay rate implied by the volatility half-life alone."""
    return math.log(2.0) / half_life_days(attr, cfg)


def learned_half_life_days(attr: str, edge, now: float | None,
                           cfg: Config = DEFAULT,
                           prior: float | None = None) -> float:
    """Personalized half-life from observed stated changes plus censoring.

    This is a staleness prior, not silent-change detection. If no learned stats
    exist (old DB rows), behavior falls back to the class prior.
    """
    prior = half_life_days(attr, cfg) if prior is None else float(prior)
    if (not getattr(cfg, "learned_volatility", False)) or edge is None:
        return prior
    if _namespace(attr) not in _curation.SINGLE_VALUE_SLOTS:
        return prior
    first = getattr(edge, "first_seen_ts", None)
    count = int(getattr(edge, "change_count", 0) or 0)
    if first is None and count <= 0:
        return prior
    if now is None:
        now = getattr(edge, "last_reinforced", first if first is not None else 0.0)
    ref = getattr(edge, "last_changed_ts", None)
    if ref is None:
        ref = first
    censor_age = max(0.0, float(now) - float(ref)) if ref is not None else 0.0
    if count <= 0:
        observed = max(prior, censor_age)
    else:
        span = max(0.0, float(now) - float(first if first is not None else ref))
        observed = span / max(float(count), 1.0)
        if count <= 1:
            observed = max(observed, censor_age)
    k = max(float(getattr(cfg, "learned_volatility_prior_strength", 3.0)), 0.0)
    w = float(count) / (float(count) + k) if count > 0 else 0.0
    blended = (1.0 - w) * prior + w * observed
    if count <= 0:
        blended = max(blended, observed)
    min_mult = float(getattr(cfg, "learned_min_multiplier", 0.2))
    max_mult = float(getattr(cfg, "learned_max_multiplier", 10.0))
    lo = max(float(getattr(cfg, "learned_min_half_life", 3.0)), prior * min_mult)
    hi = min(float(getattr(cfg, "learned_max_half_life", 7300.0)), prior * max_mult)
    return _clamp(blended, lo, max(lo, hi))


def effective_half_life_days(attr: str, edge=None, now: float | None = None,
                             cfg: Config = DEFAULT) -> float:
    prior = half_life_days(attr, cfg)
    return learned_half_life_days(attr, edge, now, cfg, prior)


def effective_volatility_lambda(attr: str, edge=None, now: float | None = None,
                                cfg: Config = DEFAULT) -> float:
    return math.log(2.0) / effective_half_life_days(attr, edge, now, cfg)


def confidence_lambda(attr: str, cfg: Config = DEFAULT, edge=None,
                      now: float | None = None) -> float:
    """Recency rate for trust. Middle classes may not be more trusting than flat."""
    if getattr(cfg, "learned_volatility", False) and edge is not None:
        return effective_volatility_lambda(attr, edge, now, cfg)
    species = species_of(attr)
    table = getattr(cfg, "confidence_half_lives", {}) or {}
    if species in table:
        lam = math.log(2.0) / max(float(table[species]), 1e-12)
    else:
        lam = volatility_lambda(attr, cfg)
    if species in {"slow", "preference", "habit", "association", "style"}:
        lam = max(lam, float(cfg.lam))
    return lam


def lambda_eff(attr: str, edge, ctx: Mapping | None = None,
               conflict: float = 0.0, cfg: Config = DEFAULT) -> float:
    """Effective decay rate for one edge when resolution decay is enabled."""
    now = _ctx(ctx, "now", None)
    if edge.source == "superseded":
        return effective_volatility_lambda(attr, edge, now, cfg)
    temp = temperature(attr, edge, conflict, cfg, ctx)
    # Current-context facts should not become long-lived just because evidence is
    # explicit; stated-vs-inferred trust belongs in verify thresholds.
    if species_of(attr) == "volatile":
        temp = 1.0
    return temp * effective_volatility_lambda(attr, edge, now, cfg)


def needs_verify(attr: str, edge, now: float, cfg: Config = DEFAULT,
                 confidence: float | None = None, conflict: float = 0.0) -> dict:
    """Return a deterministic reliability signal for agent-side verification."""
    conf_value = edge.confidence if confidence is None else confidence
    if not getattr(cfg, "volatility_confidence", False):
        return {
            "verify": False,
            "reason": "verify disabled",
            "age_halflives": 0.0,
            "confidence": conf_value,
        }
    if edge.source == "override":
        return {
            "verify": False,
            "reason": "locked override",
            "age_halflives": 0.0,
            "confidence": conf_value,
        }
    dt = max(0.0, float(now) - float(edge.last_reinforced))
    half_life = effective_half_life_days(attr, edge, now, cfg)
    age = dt / max(half_life, 1e-12)
    if max(0.0, float(conflict or 0.0)) >= cfg.verify_conflict_threshold:
        return {
            "verify": True,
            "reason": f"conflict: {float(conflict):.2f}, {species_of(attr)} fact",
            "age_halflives": age,
            "confidence": conf_value,
        }
    stated = getattr(edge, "provenance", "inferred") == "stated" or edge.source == "stated"
    threshold = cfg.verify_age_halflives_stated if stated else cfg.verify_age_halflives
    if not getattr(cfg, "verify_age_enabled", False):
        return {
            "verify": False,
            "reason": f"fresh: {age:.1f} half-lives, age-only verify disabled",
            "age_halflives": age,
            "confidence": conf_value,
        }
    verify = age >= threshold
    species = species_of(attr)
    prefix = "stale" if verify else "fresh"
    return {
        "verify": verify,
        "reason": f"{prefix}: {age:.1f} half-lives, {species} fact",
        "age_halflives": age,
        "confidence": conf_value,
    }


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
