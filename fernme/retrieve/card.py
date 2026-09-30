"""Compile the token-minimal wire card and count its tokens.

The full 0-9 graph is NEVER injected raw. We compile top-N activated links to a
compact string. Token estimate is char/4 (a standard rough proxy) unless tiktoken
is installed."""
from __future__ import annotations
from typing import Dict, List, Optional
from ..core.graph import UserGraph, AssocGraph
from ..prior.population import PopulationPrior
from ..config import Config, DEFAULT
from .. import resolution as _resolution
from .. import curation as _curation
from .activation import spread
from ..write.hebbian import effective_edge
from dataclasses import replace as _replace_edge


# Timestamps above this (~1973 in Unix seconds) are treated as wall-clock time.
_WALL_CLOCK_EPOCH = 1e8

CARD_EXCLUDE_NS = {"style", "mood", "mood_ema", "mood_prev"}


def card_exclude_namespaces(cfg: Config = DEFAULT) -> set:
    return CARD_EXCLUDE_NS | set(getattr(cfg, "card_exclude_ns", frozenset()))


def _namespace(attr: str) -> str:
    base = attr.lstrip("!")
    return base.split(":", 1)[0] if ":" in base else base


def _conflict_for(ug: UserGraph, attr: str, cfg: Config) -> float:
    edge = ug.edges.get(attr)
    if edge is None:
        return 0.0
    return max(
        (_curation.conflict_score(attr, edge, other, other_edge, cfg.w_max)
         for other, other_edge in ug.edges.items()
         if other != attr and edge.last_reinforced < other_edge.last_reinforced),
        default=0.0,
    )

try:
    import tiktoken
    _ENC = tiktoken.get_encoding("cl100k_base")
    def estimate_tokens(s: str) -> int:
        return len(_ENC.encode(s))
except Exception:
    def estimate_tokens(s: str) -> int:
        return max(1, (len(s) + 3) // 4)


def compile_card(ug: UserGraph, assoc: AssocGraph, seeds: List[str], now: float,
                 prior: Optional[PopulationPrior] = None,
                 cfg: Config = DEFAULT) -> Dict:
    """Returns {'wire': str, 'tokens': int, 'links': [...], 'numeric': {...}}."""
    act = spread(ug, assoc, seeds, now, cfg)
    exclude_ns = card_exclude_namespaces(cfg)
    # score = activation * idf (rare attrs earn slots); only stored attrs eligible
    scored = []
    read_decay = getattr(cfg, "card_read_decay", False)
    shown = {}
    # Decay runs on the user's own activity clock (their latest reinforcement),
    # not wall-clock time: a memory fades when newer evidence keeps arriving
    # without it, but a user who is simply away for months keeps their card.
    timed = [e.last_reinforced for e in ug.edges.values()
             if e.source not in ("guessed", "override")]
    activity_now = max(timed, default=0.0)
    if now > 0:
        activity_now = min(activity_now, now)
    # A card requested without a time (now=0, the MCP default) is not decayed.
    # When some memories carry wall-clock seconds and others were written with
    # ts=0 (the MCP default), the ts=0 ones have no known age and stay fresh.
    wall_clock = activity_now > _WALL_CLOCK_EPOCH
    read_decay = read_decay and now > 0
    for attr, e in ug.edges.items():
        if e.source == "superseded" or _namespace(attr) in exclude_ns:
            continue
        fast = e.fast
        fresh = 1
        if (read_decay and e.source != "guessed"
                and not (wall_clock and e.last_reinforced <= 0)):
            w_eff, fast = effective_edge(attr, e, activity_now, cfg)
            # faded memories move behind every fresh one: they only keep a slot
            # when there are not enough current memories to fill the card
            fresh = 0 if w_eff < cfg.floor else 1
            shown[attr] = _replace_edge(e, weight=w_eff, fast=fast)
        idf = prior.idf(attr) if prior else 1.0
        a = act.get(attr, 0.0)
        real = 0 if e.source == "guessed" else 1
        fast_boost = cfg.beta_fast * (fast / cfg.w_max)   # recent context lifts ranking
        salience_boost = cfg.salience_card_boost * e.salience
        scored.append((attr, (real, fresh, a * (idf + 1.0) + fast_boost + salience_boost), e))
    scored.sort(key=lambda x: x[1], reverse=True)
    top = scored[: cfg.top_n]

    parts = []
    links = []
    for attr, score, e in top:
        e = shown.get(attr, e)
        mark = "*" if e.confidence >= cfg.conf_known else "?"  # known vs guessed
        verify = (
            _resolution.needs_verify(attr, e, now, cfg,
                                     conflict=_conflict_for(ug, attr, cfg))["verify"]
            if getattr(cfg, "volatility_confidence", False)
            else False
        )
        parts.append(f"{attr}:{e.wire_weight(cfg.w_max)}{mark}"
                     + ("~verify" if verify else ""))
        link = {"attr": attr, "w": e.wire_weight(cfg.w_max),
                "known": e.confidence >= cfg.conf_known}
        if verify:
            link["verify"] = True
        links.append(link)
    def _fmt(v):
        if isinstance(v, float) and v.is_integer():
            return str(int(v))
        return str(v)
    clean_numeric = {k: v for k, v in ug.numeric.items() if not k.startswith("mood")}
    num = " ".join(f"{k}:{_fmt(v)}" for k, v in clean_numeric.items())
    wire = f"user:{ug.user} | " + " ".join(parts) + (f" | {num}" if num else "")
    return {"wire": wire, "tokens": estimate_tokens(wire), "links": links,
            "numeric": clean_numeric}
