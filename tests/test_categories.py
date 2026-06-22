"""Deterministic categories: namespace -> coarse category, no LLM, reproducible."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from fernme.categories import category_of, CATEGORIES
from fernme.service import FernService
from fernme.store.sqlite_store import SQLiteStore


def test_namespace_mapping():
    assert category_of("pref:flat-white") == "values"
    assert category_of("goal:half-marathon") == "values"
    assert category_of("rel:jonas") == "people"
    assert category_of("name:elena") == "facts"
    assert category_of("tea:earl-grey") == "media"
    assert category_of("activity:yoga") == "habits"
    assert category_of("!pref:dairy") == "emotional"        # dislikes are emotional
    assert category_of("weird:unknown") == "facts"          # default fallback


def test_graph_emits_category_per_node():
    s = FernService(store=SQLiteStore(":memory:")); s.store.set_consent("x", "u", True)
    s.observe("x", "u", "v", {"tags": ["pref:flat-white", "rel:jonas", "!pref:dairy"]})
    g = s.graph("x", "u")
    cat = {n["id"]: n.get("category") for n in g["nodes"] if n["kind"] != "user"}
    assert cat["pref:flat-white"] == "values"
    assert cat["rel:jonas"] == "people"
    assert cat["pref:dairy"] == "emotional"                 # negative -> emotional
    assert [c["key"] for c in g["categories"]] == [c["key"] for c in CATEGORIES]


def test_why_endpoint_returns_evidence():
    from fastapi.testclient import TestClient
    import fernme.api.rest as rest
    c = TestClient(rest.app)
    c.post("/consent", json={"site": "w.com", "user": "z", "granted": True})
    c.post("/observe", json={"site": "w.com", "user": "z", "type": "view", "payload": {"tags": ["pref:tea"]}})
    r = c.post("/why", json={"site": "w.com", "user": "z", "attr": "pref:tea"})
    assert r.status_code == 200
    assert "pref:tea" in str(r.json())
