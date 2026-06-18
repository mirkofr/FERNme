"""Unit tests for FERN v0 invariants. Run: pytest -q"""
import sys, os, math
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from fernme.core.graph import UserGraph, AssocGraph, Event, Edge
from fernme.write import Catalog, map_event, observe, decay
from fernme.prior import PopulationPrior
from fernme.retrieve.card import compile_card


def _cat():
    return Catalog({"p1": ["organic", "cheese", "bulk"], "p2": ["organic", "bread"]})


def test_weight_never_exceeds_max():
    ug, assoc, cat = UserGraph("s", "u"), AssocGraph("s"), _cat()
    for d in range(500):
        ev = Event("s", "u", float(d), "purchase", {"item_id": "p1", "qty": 3})
        observe(ug, assoc, ev, map_event(ev, cat))
    assert all(e.weight <= 9.0 + 1e-9 for e in ug.edges.values())
    assert ug.edges["organic"].weight > 8.0  # saturates near ceiling


def test_confidence_monotonic():
    ug, assoc, cat = UserGraph("s", "u"), AssocGraph("s"), _cat()
    last = -1.0
    for d in range(10):
        ev = Event("s", "u", float(d), "purchase", {"item_id": "p1", "qty": 1})
        observe(ug, assoc, ev, map_event(ev, cat))
        c = ug.edges["organic"].confidence
        assert c >= last
        last = c
    assert last < 1.0


def test_decay_drops_stale_edges():
    ug, assoc, cat = UserGraph("s", "u"), AssocGraph("s"), _cat()
    ev = Event("s", "u", 0.0, "purchase", {"item_id": "p1", "qty": 1})
    observe(ug, assoc, ev, map_event(ev, cat))
    n_before = ug.n_edges()
    dropped = decay(ug, now=10_000.0)  # very stale
    assert dropped == n_before and ug.n_edges() == 0


def test_override_never_decays():
    ug, assoc = UserGraph("s", "u"), AssocGraph("s")
    ug.edges["organic"] = Edge(weight=5.0, confidence=1.0, source="override", last_reinforced=0.0)
    decay(ug, now=10_000.0)
    assert "organic" in ug.edges and ug.edges["organic"].weight == 5.0


def test_negative_signal_is_separate_edge():
    ug, assoc, cat = UserGraph("s", "u"), AssocGraph("s"), _cat()
    ev = Event("s", "u", 0.0, "decline", {"item_id": "p1", "qty": 1})
    observe(ug, assoc, ev, map_event(ev, cat))
    assert any(a.startswith("!") for a in ug.edges)  # negative edges prefixed '!'


def test_differential_threshold():
    pp = PopulationPrior("s")
    for u in range(4):
        g = UserGraph("s", f"u{u}")
        g.edges["organic"] = Edge(weight=8.0, confidence=0.9, source="known")
        pp.update_from_user(g)
    assert pp.mean("organic") == 8.0
    assert not pp.deviates("organic", 8.5)   # within theta -> read-through to prior
    assert pp.deviates("organic", 2.0)       # far below -> store as deviation


def test_cold_start_all_guessed():
    pp = PopulationPrior("s")
    for u in range(3):
        g = UserGraph("s", f"u{u}")
        g.edges["organic"] = Edge(weight=7.0, confidence=0.9, source="known")
        pp.update_from_user(g)
    new = UserGraph("s", "new")
    pp.cold_start(new)
    assert new.n_edges() > 0
    assert all(e.source == "guessed" for e in new.edges.values())


def test_card_token_cost_is_bounded():
    ug, assoc, cat = UserGraph("s", "u"), AssocGraph("s"), _cat()
    for d in range(300):
        ev = Event("s", "u", float(d), "purchase", {"item_id": "p1", "qty": 2})
        observe(ug, assoc, ev, map_event(ev, cat))
    card = compile_card(ug, assoc, seeds=["cheese"], now=300.0)
    assert card["tokens"] < 80  # stays tiny no matter how many interactions
    assert "user:u" in card["wire"]
