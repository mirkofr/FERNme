"""Private collective priors (#1): k-anonymity suppression + bounded-mean DP.
Run: pytest -q tests/test_dp.py"""
import sys, os, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from fernme.prior.population import PopulationPrior
from fernme.core.graph import UserGraph, Edge
from fernme.dp import PrivatePrior
from fernme.service import FernService


def _base(with_secret=True):
    """40 users like mornings, 20 need wheelchair access, (optionally) 1 has a
    unique secret trait. Non-commerce on purpose (a clinic portal)."""
    pp = PopulationPrior("clinic")
    for i in range(40):
        g = UserGraph("clinic", f"u{i}")
        g.edges["morning_pref"] = Edge(weight=7.0, confidence=0.9, source="known")
        if i < 20:
            g.edges["wheelchair_access"] = Edge(weight=5.0, confidence=0.9, source="known")
        if with_secret and i == 0:
            g.edges["rare_secret_condition"] = Edge(weight=9.0, confidence=0.9, source="known")
        pp.update_from_user(g)
    return pp


def test_rare_trait_is_suppressed():
    pp = PrivatePrior(_base(), epsilon=1.0, k=5)
    assert "morning_pref" in pp.released_attrs()          # common -> released
    assert "wheelchair_access" in pp.released_attrs()     # 20 users -> released
    assert "rare_secret_condition" not in pp.released_attrs()  # n=1 < k -> ALWAYS dropped


def test_utility_preserved_for_common_attrs():
    pp = PrivatePrior(_base(), epsilon=1.0, k=5)
    assert abs(pp.mean("morning_pref") - 7.0) < 2.0       # near true mean despite noise


def test_noise_is_real():
    a = PrivatePrior(_base(), epsilon=1.0, k=5, seed=1).mean("morning_pref")
    b = PrivatePrior(_base(), epsilon=1.0, k=5, seed=2).mean("morning_pref")
    assert a != b                                         # different noise draws


def test_neighboring_dataset_no_leak():
    # the unique-trait user's presence must not surface in the private prior
    with_user = PrivatePrior(_base(with_secret=True), epsilon=1.0, k=5)
    without = PrivatePrior(_base(with_secret=False), epsilon=1.0, k=5)
    assert "rare_secret_condition" not in with_user.released_attrs()
    assert "rare_secret_condition" not in without.released_attrs()  # indistinguishable


def test_private_cold_start_never_seeds_rare():
    fd, p = tempfile.mkstemp(suffix=".db"); os.close(fd); os.remove(p)
    svc = FernService(p)
    for i in range(40):
        svc.consent("clinic", f"u{i}", True)
        for _ in range(2):
            tags = ["morning_pref"] + (["wheelchair_access"] if i < 20 else [])
            if i == 0: tags.append("rare_secret_condition")
            svc.observe("clinic", f"u{i}", "visit", {"tags": tags})
    svc.prior_refresh("clinic")
    pp = svc.private_prior("clinic", epsilon=1.0, k=5)
    newcomer = UserGraph("clinic", "newbie")
    pp.cold_start(newcomer, svc.cfg)
    seeded = set(newcomer.edges)
    assert "morning_pref" in seeded                       # newcomer benefits from crowd
    assert "rare_secret_condition" not in seeded          # but the rare trait never leaks
