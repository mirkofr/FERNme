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
    source: str = "known"        # known | guessed | override | superseded
    last_reinforced: float = 0.0 # day index of last reinforcement
    hits: int = 0                # independent observations
    fast: float = 0.0            # fast-timescale component (recent context); decays quickly
    salience: float = 0.0        # 0..1 significance: high salience -> slower forgetting
    provenance: str = "inferred" # stated | inferred
    change_count: int = 0        # stated/override supersessions counted for volatility learning
    first_seen_ts: Optional[float] = None
    last_changed_ts: Optional[float] = None
    last_change_counted_ts: Optional[float] = None

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
    co-use). Most users read this directly; rare per-user overrides not in v0.

    `edges` is the source of truth. `_adj` is a parallel adjacency index so
    neighbors() is O(degree) instead of O(all edges) -- without it, spreading
    activation re-scans every association edge for every node on every recall,
    which is O(nodes x edges x hops) and blows past 200ms on a few hundred
    memories. The index is built lazily on first read and kept in sync by
    set_edge(); direct bulk loads just trigger a one-time reindex."""
    site: str
    edges: Dict[Tuple[str, str], float] = field(default_factory=dict)
    # node -> {neighbor: weight}; not an init arg, rebuilt from edges on demand
    _adj: Dict[str, Dict[str, float]] = field(default_factory=dict, init=False,
                                              repr=False, compare=False)

    @staticmethod
    def key(a: str, b: str) -> Tuple[str, str]:
        return (a, b) if a <= b else (b, a)

    def get(self, a: str, b: str) -> float:
        return self.edges.get(self.key(a, b), 0.0)

    def reindex(self) -> None:
        """Rebuild the adjacency index from `edges` (one linear pass)."""
        adj: Dict[str, Dict[str, float]] = {}
        for (x, y), w in self.edges.items():
            adj.setdefault(x, {})[y] = w
            adj.setdefault(y, {})[x] = w
        self._adj = adj

    def set_edge(self, a: str, b: str, w: float) -> None:
        """Upsert an association weight, keeping `edges` and `_adj` in sync."""
        if not self._adj and self.edges:
            self.reindex()                 # ensure index is complete first
        self.edges[self.key(a, b)] = w
        self._adj.setdefault(a, {})[b] = w
        self._adj.setdefault(b, {})[a] = w

    def neighbors(self, a: str) -> List[Tuple[str, float]]:
        if not self._adj and self.edges:   # lazily build after a bulk load
            self.reindex()
        nb = self._adj.get(a)
        return list(nb.items()) if nb else []


@dataclass
class Event:
    site: str
    user: str
    ts: float                    # day index
    type: str                    # purchase | browse | booking | decline | return ...
    payload: dict = field(default_factory=dict)
    attrs: List[Tuple[str, float]] = field(default_factory=list)  # (attr, magnitude) after mapping
