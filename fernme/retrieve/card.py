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

_CL100K_URL = "https://openaipublic.blob.core.windows.net/encodings/cl100k_base.tiktoken"
_ENC = None
_ENC_TRIED = False


def _tiktoken_cached() -> bool:
    """True if tiktoken can load cl100k_base without a network download."""
    import hashlib
    import os
    import tempfile
    cache_dir = (os.environ.get("TIKTOKEN_CACHE_DIR")
                 or os.environ.get("DATA_GYM_CACHE_DIR")
                 or os.path.join(tempfile.gettempdir(), "data-gym-cache"))
    if not cache_dir:
        return False
    return os.path.exists(os.path.join(cache_dir, hashlib.sha1(_CL100K_URL.encode()).hexdigest()))


def _encoder():
    """Exact token counts when tiktoken's encoding is already on disk; otherwise
    FERNme stays offline and estimates. Set FERNME_TOKENIZER_DOWNLOAD=1 to let
    tiktoken fetch its encoding once."""
    global _ENC, _ENC_TRIED
    if _ENC_TRIED:
        return _ENC
    _ENC_TRIED = True
    import os
    allow = os.environ.get("FERNME_TOKENIZER_DOWNLOAD", "").strip().lower() in (
        "1", "true", "yes", "on")
    try:
        if allow or _tiktoken_cached():
            import tiktoken
            _ENC = tiktoken.get_encoding("cl100k_base")
    except Exception:
        _ENC = None
    return _ENC


def estimate_tokens(s: str) -> int:
    enc = _encoder()
    if enc is not None:
        return len(enc.encode(s))
    return max(1, (len(s) + 3) // 4)


DECAY_CLOCK_KEY = "_decay_clock"


def _superseded_slot_values(ug: UserGraph) -> Dict[str, int]:
    """{attr: 0} for older values in single-value slots that a newer, confirmed
    value has replaced (see Config.card_single_value_latest)."""
    from ..curation import SINGLE_VALUE_SLOTS
    by_slot: Dict[str, list] = {}
    for attr, e in ug.edges.items():
        if attr.startswith("!") or e.source in ("guessed", "superseded", "override"):
            continue
        ns = attr.split(":", 1)[0]
        if ns in SINGLE_VALUE_SLOTS and ":" in attr:
            by_slot.setdefault(ns, []).append((attr, e))
    out: Dict[str, int] = {}
    for items in by_slot.values():
        confirmed = [(a, e) for a, e in items if e.provenance == "stated" or e.hits >= 2]
        if len(items) < 2 or not confirmed:
            continue
        if any(e.last_reinforced <= 0 for _, e in items):
            # A value written without a time (MCP/REST default ts=0) has no known
            # order, so "newest" cannot be decided: leave the slot to ranking.
            continue
        latest = max(confirmed, key=lambda ae: ae[1].last_reinforced)
        for a, e in items:
            if a != latest[0] and e.last_reinforced < latest[1].last_reinforced:
                out[a] = 0
    return out


def faded_view(ug: UserGraph, now: float, cfg: Config = DEFAULT):
    """Read-time decay for the card, without touching storage.

    Returns ``(fresh, shown)``: ``fresh[attr]`` is 0 for memories that have faded
    below ``floor`` (they rank behind every current memory and only keep a slot
    when there are not enough current ones), and ``shown[attr]`` is the edge with
    its decayed weight/fast lane for display.

    Decay runs on the user's own activity clock (their latest reinforcement), not
    wall-clock time: a memory fades when newer evidence keeps arriving without it,
    while a user who is simply away keeps their card. A card requested without a
    time (now=0, the MCP default) is not decayed, and when some memories carry
    wall-clock seconds while others were written with ts=0, the ts=0 ones have no
    known age and stay fresh."""
    fresh, shown = {}, {}
    if getattr(cfg, "card_single_value_latest", False):
        fresh.update(_superseded_slot_values(ug))
    if not getattr(cfg, "card_read_decay", False) or now <= 0:
        return fresh, shown
    timed = [e.last_reinforced for e in ug.edges.values()
             if e.source not in ("guessed", "override")]
    activity_now = min(max(timed, default=0.0), now)
    wall_clock = activity_now > _WALL_CLOCK_EPOCH
    clock = ug.numeric.get(DECAY_CLOCK_KEY)
    for attr, e in ug.edges.items():
        if e.source in ("guessed", "superseded") or (wall_clock and e.last_reinforced <= 0):
            continue
        w_eff, fast = effective_edge(attr, e, activity_now, cfg, decay_clock=clock)
        fresh[attr] = 0 if (w_eff < cfg.floor or fresh.get(attr) == 0) else 1
        shown[attr] = _replace_edge(e, weight=w_eff, fast=fast)
    return fresh, shown


def compile_card(ug: UserGraph, assoc: AssocGraph, seeds: List[str], now: float,
                 prior: Optional[PopulationPrior] = None,
                 cfg: Config = DEFAULT) -> Dict:
    """Returns {'wire': str, 'tokens': int, 'links': [...], 'numeric': {...}}."""
    act = spread(ug, assoc, seeds, now, cfg)
    exclude_ns = card_exclude_namespaces(cfg)
    # score = activation * idf (rare attrs earn slots); only stored attrs eligible
    scored = []
    fresh_of, shown = faded_view(ug, now, cfg)
    for attr, e in ug.edges.items():
        if e.source == "superseded" or _namespace(attr) in exclude_ns:
            continue
        fresh = fresh_of.get(attr, 1)
        fast = shown[attr].fast if attr in shown else e.fast
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
    clean_numeric = {k: v for k, v in ug.numeric.items()
                     if not k.startswith(("mood", "_"))}
    num = " ".join(f"{k}:{_fmt(v)}" for k, v in clean_numeric.items())
    wire = f"user:{ug.user} | " + " ".join(parts) + (f" | {num}" if num else "")
    return {"wire": wire, "tokens": estimate_tokens(wire), "links": links,
            "numeric": clean_numeric}
