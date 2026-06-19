"""Core data structures: the per-user sparse preference graph, the shared
associative graph, and the event record (the Cabinet)."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, List, Tuple, Optional


# attribute "kind": categorical | behavioral | negative
@dataclass
class Edge:
    weight: float = 0.0          # continuous 0..w_max internally; rounded on the wire
    confidence: float = 0.0      # 0..1, drives verify-vs-act gating
    source: str = "known"        # known | guessed | override
    last_reinforced: float = 0.0 # day index of last reinforcement
    hits: int = 0                # independent observations
    fast: float = 0.0            # fast-timescale component (recent context); decays quickly
    salience: float = 0.0        # 0..1 significance: high salience -> slower forgetting

    def wire_weight(self, w_max: float = 9.0) -> int:
        return max(0, min(int(round(self.weight)), int(w_max)))


@dataclass
class UserGraph:
    """Sparse: only stores attributes where the user deviates from the prior,
    plus numeric side-fields for quantities a graph edge can't hold."""
    site: str
    user: str
    edges: Dict[str, Edge] = field(default_factory=dict)
    numeric: Dict[str, float] = field(default_factory=dict)
    # reinforcement timestamps per attr (for ACT-R base-level activation)
    history: Dict[str, List[float]] = field(default_factory=dict)

    def get(self, attr: str) -> Optional[Edge]:
        return self.edges.get(attr)

    def n_edges(self) -> int:
        return len(self.edges)


@dataclass
class AssocGraph:
    """Shared per-site attribute<->attribute association weights (Hebbian
    co-use). Most users read this directly; rare per-user overrides not in v0."""
    site: str
    edges: Dict[Tuple[str, str], float] = field(default_factory=dict)

    @staticmethod
    def key(a: str, b: str) -> Tuple[str, str]:
        return (a, b) if a <= b else (b, a)

    def get(self, a: str, b: str) -> float:
        return self.edges.get(self.key(a, b), 0.0)

    def neighbors(self, a: str) -> List[Tuple[str, float]]:
        out = []
        for (x, y), w in self.edges.items():
            if x == a:
                out.append((y, w))
            elif y == a:
                out.append((x, w))
        return out


@dataclass
class Event:
    site: str
    user: str
    ts: float                    # day index
    type: str                    # purchase | browse | booking | decline | return ...
    payload: dict = field(default_factory=dict)
    attrs: List[Tuple[str, float]] = field(default_factory=list)  # (attr, magnitude) after mapping
