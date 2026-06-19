"""Salience: emotional/behavioral significance modulates forgetting.
High-salience edges decay slowly; default (beta=0) changes nothing."""
import sys, os, math
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from dataclasses import replace
from fernme.config import DEFAULT
from fernme.core.graph import UserGraph, AssocGraph, Event, Edge
from fernme.write.hebbian import observe, decay
from fernme.service import FernService
from fernme.store.sqlite_store import SQLiteStore


def _seed(cfg, salient_intensity):
    ug = UserGraph("s", "u"); ag = AssocGraph("s")
    # one neutral and one strongly-salient single observation, same starting weight
    observe(ug, ag, Event("s","u",0.0,"v",{}), [("pref:neutral", 5.0)], cfg)
    observe(ug, ag, Event("s","u",0.0,"v",{}), [("pref:intense", 5.0)], cfg,
            salience={"pref:intense": salient_intensity})
    return ug, ag


def test_salience_slows_forgetting_when_enabled():
    cfg = replace(DEFAULT, salience_beta=0.9)
    ug, ag = _seed(cfg, 1.0)
    assert ug.edges["pref:intense"].salience >= 0.9
    for t in range(1, 120):                      # ~4 months of no reinforcement
        decay(ug, now=float(t), cfg=cfg)
    # the salient memory survives; the neutral one is forgotten (dropped below floor)
    assert "pref:intense" in ug.edges
    assert "pref:neutral" not in ug.edges


def test_default_off_is_backward_compatible():
    cfg = replace(DEFAULT, salience_beta=0.0)   # OFF
    ug, ag = _seed(cfg, 1.0)
    for t in range(1, 120):
        decay(ug, now=float(t), cfg=cfg)
    # with salience OFF, the intense edge gets no retention advantage -> both gone together
    assert ("pref:intense" in ug.edges) == ("pref:neutral" in ug.edges)


def test_negative_edges_get_salience_floor():
    cfg = DEFAULT
    ug = UserGraph("s","u"); ag = AssocGraph("s")
    observe(ug, ag, Event("s","u",0.0,"v",{}), [("!pref:mushrooms", 5.0)], cfg)
    assert ug.edges["!pref:mushrooms"].salience >= cfg.salience_neg


def test_outcome_adds_salience():
    svc = FernService(store=SQLiteStore(":memory:"))
    svc.store.set_consent("s","u",True)
    svc.observe("s","u","view",{"tags":["pref:plan"]})
    svc.record_outcome("s","u", success=False, attrs=["pref:plan"], weight=1.0)
    e = svc.store.load_user("s","u").edges["pref:plan"]
    assert e.salience > 0   # a failed outcome is memorable


def test_salience_persists_round_trip():
    st = SQLiteStore(":memory:")
    svc = FernService(store=st); svc.store.set_consent("s","u",True)
    svc.observe("s","u","view",{"tags":["pref:x"],"intensity":0.8})
    e = svc.store.load_user("s","u").edges["pref:x"]
    assert abs(e.salience - 0.8) < 1e-6        # survived save->load
