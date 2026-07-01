"""Multi-timescale memory (#7): fast lane (recent context) vs slow lane
(durable identity). Run: pytest -q tests/test_timescale.py"""
import sys, os, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from dataclasses import replace
from fernme.config import DEFAULT
from fernme.core.graph import UserGraph, AssocGraph, Event
from fernme.write import Catalog, map_event, observe, decay
from fernme.retrieve.card import compile_card
from fernme.store.sqlite_store import SQLiteStore


def _obs(ug, ag, attr, ts, cfg=DEFAULT):
    ev = Event("s", "u", float(ts), "x", {"tags": [attr]})
    observe(ug, ag, ev, map_event(ev, Catalog()), cfg)


def test_fast_fades_faster_than_slow():
    cfg = replace(DEFAULT, resolution=False)
    ug, ag = UserGraph("s", "u"), AssocGraph("s")
    _obs(ug, ag, "topic", 0, cfg)
    e = ug.edges["topic"]; w0, f0 = e.weight, e.fast
    assert f0 > 0 and w0 > 0
    decay(ug, now=5.0, cfg=cfg)
    assert e.fast / f0 < e.weight / w0          # fast lane decays much more
    decay(ug, now=60.0, cfg=cfg)
    assert e.fast < 0.05 * f0                    # after disuse, fast ~gone
    assert e.weight > 0                          # slow identity persists


def test_recent_context_surfaces_in_ranking():
    cfg = replace(DEFAULT, resolution=False)
    ug, ag = UserGraph("s", "u"), AssocGraph("s")
    for d in range(3):                           # build two equal long-standing traits
        _obs(ug, ag, "topic_a", d, cfg); _obs(ug, ag, "topic_b", d, cfg)
    decay(ug, now=40.0, cfg=cfg)                 # both fast lanes fade
    _obs(ug, ag, "topic_a", 40, cfg)             # A gets a fresh, recent touch
    decay(ug, now=40.0, cfg=cfg)
    order = [l["attr"] for l in compile_card(ug, ag, seeds=[], now=40.0,
                                             cfg=cfg)["links"]]
    assert order.index("topic_a") < order.index("topic_b")   # recent context ranks first


def test_fast_persists_roundtrip():
    fd, p = tempfile.mkstemp(suffix=".db"); os.close(fd); os.remove(p)
    st = SQLiteStore(p)
    ug, ag = UserGraph("s", "u"), AssocGraph("s")
    _obs(ug, ag, "topic", 0)
    st.save_user(ug)
    assert st.load_user("s", "u").edges["topic"].fast > 0   # fast survives persistence
