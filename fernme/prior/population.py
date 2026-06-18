"""Population prior + differential encoding + IDF cold-start.

The novel-ish claim (file 09): a new user inherits the population baseline and we
store only deviations from it -> useful on turn one, near-zero marginal storage.
This module is built so the 'differential vs. user-only sparse edges' ablation is
a one-line switch (use_prior=True/False)."""
from __future__ import annotations
import math
from typing import Dict, List, Tuple
from ..core.graph import UserGraph, Edge
from ..config import Config, DEFAULT


class PopulationPrior:
    def __init__(self, site: str):
        self.site = site
        self._sum: Dict[str, float] = {}      # running sum of user weights per attr
        self._n: Dict[str, int] = {}          # # users contributing to that attr
        self.n_users: int = 0

    def update_from_user(self, ug: UserGraph) -> None:
        """Incremental: fold a user's edges into the running mean."""
        self.n_users += 1
        seen = set()
        for attr, e in ug.edges.items():
            if e.source == "guessed":
                continue  # don't let guesses pollute the prior
            self._sum[attr] = self._sum.get(attr, 0.0) + e.weight
            self._n[attr] = self._n.get(attr, 0) + 1
            seen.add(attr)

    def mean(self, attr: str) -> float:
        n = self._n.get(attr, 0)
        return self._sum[attr] / n if n else 0.0

    def idf(self, attr: str) -> float:
        # rarity weight (Spaerck Jones): rare attrs carry more signal
        n = self._n.get(attr, 0)
        return math.log((self.n_users + 1.0) / (1.0 + n))

    def deviates(self, attr: str, weight: float, cfg: Config = DEFAULT) -> bool:
        return abs(weight - self.mean(attr)) > cfg.theta

    def cold_start(self, ug: UserGraph, cfg: Config = DEFAULT, k: int = None) -> None:
        """Seed a brand-new user's graph with 'guessed' edges from the prior,
        ranked by mean*idf so rare-but-distinctive attrs win the slots. The agent
        verifies these (low confidence) rather than acting silently."""
        k = k or cfg.top_n
        scored = [(attr, self.mean(attr) * self.idf(attr)) for attr in self._n]
        scored.sort(key=lambda x: x[1], reverse=True)
        for attr, _ in scored[:k]:
            if attr in ug.edges:
                continue
            ug.edges[attr] = Edge(weight=self.mean(attr), confidence=0.15,
                                  source="guessed", last_reinforced=0.0, hits=0)

    def effective_weight(self, ug: UserGraph, attr: str, use_prior: bool = True) -> float:
        """Read-through: stored user weight if present, else the prior (when
        use_prior). This is what makes storage 'deviations only'."""
        e = ug.edges.get(attr)
        if e is not None:
            return e.weight
        return self.mean(attr) if use_prior else 0.0
