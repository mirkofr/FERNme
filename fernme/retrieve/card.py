"""Compile the token-minimal wire card and count its tokens.

The full 0-9 graph is NEVER injected raw. We compile top-N activated links to a
compact string. Token estimate is char/4 (a standard rough proxy) unless tiktoken
is installed."""
from __future__ import annotations
from typing import Dict, List, Optional
from ..core.graph import UserGraph, AssocGraph
from ..prior.population import PopulationPrior
from ..config import Config, DEFAULT
from .activation import spread

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
        idf = prior.idf(attr) if prior else 1.0
        a = act.get(attr, 0.0)
        real = 0 if e.source == "guessed" else 1
        fast_boost = cfg.beta_fast * (e.fast / cfg.w_max)   # recent context lifts ranking
        scored.append((attr, (real, a * (idf + 1.0) + fast_boost), e))
    scored.sort(key=lambda x: x[1], reverse=True)
    top = scored[: cfg.top_n]

    parts = []
    links = []
    for attr, score, e in top:
        mark = "*" if e.confidence >= cfg.conf_known else "?"  # known vs guessed
        parts.append(f"{attr}:{e.wire_weight(cfg.w_max)}{mark}")
        links.append({"attr": attr, "w": e.wire_weight(cfg.w_max),
                      "known": e.confidence >= cfg.conf_known})
    def _fmt(v):
        if isinstance(v, float) and v.is_integer():
            return str(int(v))
        return str(v)
    num = " ".join(f"{k}:{_fmt(v)}" for k, v in ug.numeric.items())
    wire = f"user:{ug.user} | " + " ".join(parts) + (f" | {num}" if num else "")
    return {"wire": wire, "tokens": estimate_tokens(wire), "links": links,
            "numeric": dict(ug.numeric)}
