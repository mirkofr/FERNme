"""Private collective priors (#1) — the network-effect cold-start single-user
memories structurally can't have, made safe across real users by TWO separate,
well-understood mechanisms:

  1. k-ANONYMITY SUPPRESSION (deterministic): an attribute is released only if at
     least k users have it. A unique/rare trait (n < k) is ALWAYS dropped, so the
     prior can never fingerprint a near-unique individual.
  2. BOUNDED-MEAN DIFFERENTIAL PRIVACY: for surviving attributes, the released
     mean gets Laplace noise calibrated to sensitivity ~ w_max / n (changing one
     member moves an n-member mean by at most w_max/n). So even inside a group you
     can't infer any individual's exact value.

HONEST SCOPE: a user contributes to several attributes, so releases COMPOSE; we
divide the budget by `max_contrib` to bound total epsilon per user. A production
deployment still needs a formal privacy accountant. Defaults are illustrative."""
from __future__ import annotations
import math
import numpy as np


class PrivatePrior:
    def __init__(self, base, epsilon: float = 1.0, k: int = 5, w_max: float = 9.0,
                 max_contrib: int = 8, seed: int | None = 0):
        # base duck-types PopulationPrior: needs ._n, ._sum, .n_users
        self.site = getattr(base, "site", "?")
        self.n_users = base.n_users
        self.eps = epsilon; self.k = k; self.w_max = w_max
        rng = np.random.default_rng(seed)
        eps_attr = epsilon / max_contrib                # bound composition per user
        self._means: dict[str, float] = {}
        self._counts: dict[str, int] = {}
        self._suppressed = 0
        for attr, n in base._n.items():
            if n < k:                                   # (1) k-anonymity: rare -> drop
                self._suppressed += 1
                continue
            true_mean = base._sum[attr] / n
            scale = (w_max / n) / eps_attr              # (2) bounded-mean Laplace
            noisy = true_mean + rng.laplace(0.0, scale)
            self._means[attr] = min(w_max, max(0.0, noisy))
            self._counts[attr] = n
        self.n_released = len(self._means)

    def mean(self, attr: str) -> float:
        return self._means.get(attr, 0.0)

    def idf(self, attr: str) -> float:
        n = self._counts.get(attr, 0)
        return math.log((self.n_users + 1.0) / (1.0 + n))

    def released_attrs(self):
        return list(self._means.keys())

    def cold_start(self, ug, cfg, k: int | None = None):
        """Seed a new user from the PRIVATE prior only — suppressed (rare) traits
        can never be seeded, so no individual leaks into a newcomer's profile."""
        from .core.graph import Edge
        k = k or cfg.top_n
        scored = sorted(self._means.items(),
                        key=lambda kv: -(kv[1] * (self.idf(kv[0]) + 1.0)))
        for attr, _ in scored[:k]:
            if attr not in ug.edges:
                ug.edges[attr] = Edge(weight=self._means[attr], confidence=0.15,
                                      source="guessed", last_reinforced=0.0, hits=0)
