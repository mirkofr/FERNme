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


CARD_EXCLUDE_NS = {"style", "mood", "mood_ema", "mood_prev"}


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
    # score = activation * idf (rare attrs earn slots); only stored attrs eligible
    scored = []
    for attr, e in ug.edges.items():
        if e.source == "superseded" or _namespace(attr) in CARD_EXCLUDE_NS:
            continue
        idf = prior.idf(attr) if prior else 1.0
        a = act.get(attr, 0.0)
        real = 0 if e.source == "guessed" else 1
        fast_boost = cfg.beta_fast * (e.fast / cfg.w_max)   # recent context lifts ranking
        salience_boost = cfg.salience_card_boost * e.salience
        scored.append((attr, (real, a * (idf + 1.0) + fast_boost + salience_boost), e))
    scored.sort(key=lambda x: x[1], reverse=True)
    top = scored[: cfg.top_n]

    parts = []
    links = []
    for attr, score, e in top:
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
