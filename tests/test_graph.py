"""Graph visualization endpoint: nodes + edges for the memory graph view."""
import sys, os
import json
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from demo.elena.entity_scene import populate_elena_entities
from fernme.service import FernService
from fernme.store.sqlite_store import SQLiteStore


def _svc():
    s = FernService(store=SQLiteStore(":memory:"))
    s.store.set_consent("demo.com", "ana", True)
    s.store.set_consent("demo.com", "ben", True)
    s.observe("demo.com", "ana", "view", {"tags": ["likes:hiking", "topic:trail-running", "!likes:crowds"]})
    s.observe("demo.com", "ana", "view", {"tags": ["likes:hiking", "topic:trail-running"]})
    s.observe("demo.com", "ben", "view", {"tags": ["likes:hiking", "topic:photography"]})
    return s


def test_single_user_subgraph():
    s = _svc()
    g = s.graph("demo.com", "ana")
    assert "user" in {n["kind"] for n in g["nodes"]}
    assert g["stats"]["users"] == 1
    user_nodes = [n for n in g["nodes"] if n["kind"] == "user"]
    assert user_nodes[0]["label"] == "ana"
    assert any(e.get("negative") for e in g["edges"])


def test_whole_site_has_shared_attribute():
    s = _svc()
    g = s.graph("demo.com")
    assert g["stats"]["users"] == 2
    assert "likes:hiking" in {n["label"] for n in g["nodes"]}
    inc = [e for e in g["edges"] if e["target"] == "likes:hiking"]
    assert len(inc) == 2


def test_consent_is_required_for_named_user():
    s = _svc()
    s.store.set_consent("demo.com", "ana", False)
    try:
        s.graph("demo.com", "ana")
        assert False, "expected consent error"
    except Exception as e:
        assert "consent" in str(e).lower()


def test_whole_site_skips_unconsented_users():
    s = _svc()
    s.store.set_consent("demo.com", "ben", False)
    g = s.graph("demo.com")
    assert g["stats"]["users"] == 1
    assert all(n["label"] != "ben" for n in g["nodes"] if n["kind"] == "user")


def test_node_size_tracks_strength():
    s = _svc()
    g = s.graph("demo.com", "ana")
    hiking = next(n for n in g["nodes"] if n["label"] == "likes:hiking")
    assert hiking["size"] > 0


def test_graph_includes_hierarchy_without_removing_flat_view():
    s = FernService(store=SQLiteStore(":memory:"))
    s.store.set_consent("demo.com", "ana", True)
    s.observe("demo.com", "ana", "view", {
        "tags": ["person:mrs-reyes", "project:orbit-newmarket", "connection:helped-connect-orbitlabs"]
    })

    g = s.graph("demo.com", "ana")
    assert "nodes" in g and "edges" in g
    assert "hierarchy" in g
    anchors = {n["id"] for n in g["hierarchy"]["anchors"]}
    assert {"person:mrs-reyes", "project:orbit-newmarket"} <= anchors
    assert g["hierarchy"]["assignments"]["connection:helped-connect-orbitlabs"] in anchors


def test_graph_payload_shape_is_unchanged_without_entities():
    s = _svc()
    g = s.graph("demo.com", "ana", hierarchy=False)
    assert list(g.keys()) == ["nodes", "edges", "categories", "cats", "stats"]
    assert "entities" not in g
    assert "entity_aliases" not in g
    assert "entity_relations" not in g
    assert json.dumps(g, sort_keys=True, separators=(",", ":")) == json.dumps({
        "cats": g["cats"],
        "categories": g["categories"],
        "edges": g["edges"],
        "nodes": g["nodes"],
        "stats": g["stats"],
    }, sort_keys=True, separators=(",", ":"))


def test_elena_fixture_graph_includes_entity_layer():
    s = FernService(store=SQLiteStore(":memory:"))
    s.store.set_consent("elena.journal", "elena", True)
    populate_elena_entities(s)
    g = s.graph("elena.journal", "elena", hierarchy=False)

    assert {"entities", "entity_aliases", "entity_relations"} <= set(g)
    entities = {e["display_name"]: e for e in g["entities"]}
    assert {"Elena", "Jonas", "Daniel", "memory-journal-platform"} <= set(entities)
    assert entities["Elena"]["node_id"] == "user:elena"
    assert entities["Elena"]["owner_entity"] is True
    assert entities["Jonas"]["fields"] == [{
        "entity_id": entities["Jonas"]["entity_id"],
        "field": "handle",
        "value": "@jonas-k-demo",
        "provenance": "stated",
        "ts": 1000.1,
    }]

    jonas_nodes = [n for n in g["nodes"] if n.get("entity_display_name") == "Jonas"]
    assert len(jonas_nodes) == 1
    assert "person:jonas" in jonas_nodes[0]["entity_aliases"]
    assert "person:jonas-k" in jonas_nodes[0]["entity_aliases"]
    assert "person:jonas-k" in jonas_nodes[0]["collapsed_aliases"]
    assert "person:jonas-k" not in {n["id"] for n in g["nodes"]}
    assert g["entity_aliases"]["person:jonas"] == g["entity_aliases"]["person:jonas-k"]
    node_ids = {n["id"] for n in g["nodes"]}
    assert "person:elena" not in node_ids
    owner_node = next(n for n in g["nodes"] if n["id"] == "user:elena")
    assert owner_node["entity_display_name"] == "Elena"
    assert owner_node["owner_entity"] is True

    relation_edges = [e for e in g["edges"] if e.get("entity_relation")]
    assert {"friend_of", "colleague_of", "works_on"} <= {e["relation"] for e in relation_edges}
    assert all(e.get("label") == e["relation"] for e in relation_edges)
    assert any("user:elena" in (e["source"], e["target"]) for e in relation_edges)
    assert all(e["source"] in node_ids for e in relation_edges)
    assert all(e["target"] in node_ids for e in relation_edges)
    assert all(e["source"] != e["target"] for e in g["edges"])


def test_elena_fixture_graph_contains_only_fictional_cast():
    s = FernService(store=SQLiteStore(":memory:"))
    s.store.set_consent("elena.journal", "elena", True)
    populate_elena_entities(s)
    g = s.graph("elena.journal", "elena", hierarchy=False)
    assert {e["display_name"] for e in g["entities"]} == {
        "Elena", "Jonas", "Daniel", "memory-journal-platform"
    }
    assert set(g["entity_aliases"]) == {
        "person:elena",
        "name:elena-sofia-markovic",
        "person:jonas",
        "person:jonas-k",
        "rel:jonas",
        "person:daniel",
        "rel:daniel",
        "project:memory-journal-platform",
    }


def test_memory_graph_is_cross_surface():
    """One owner, memories assembled across surfaces (web + pc + phone) with provenance."""
    s = FernService(store=SQLiteStore(":memory:"))
    for site, u in [("shop.com", "a1"), ("pc:desktop", "a2"), ("phone:ios", "a3")]:
        s.store.set_consent(site, u, True)
    s.observe("shop.com", "a1", "view", {"tags": ["likes:oat-milk", "!likes:dairy"]})
    s.observe("pc:desktop", "a2", "view", {"tags": ["likes:dark-mode", "topic:python"]})
    s.observe("phone:ios", "a3", "view", {"tags": ["likes:dark-mode", "time:morning"]})
    for site, u in [("shop.com", "a1"), ("pc:desktop", "a2"), ("phone:ios", "a3")]:
        s.link_identity("mirko", site, u)

    g = s.memory_graph("mirko")
    # one owner node, three surfaces
    owners = [n for n in g["nodes"] if n["kind"] == "owner"]
    assert len(owners) == 1 and owners[0]["label"] == "mirko"
    fams = {sf["family"] for sf in g["surfaces"]}
    assert {"web", "pc", "phone"} <= fams
    # a memory seen on two surfaces carries both as provenance
    dm = next(n for n in g["nodes"] if n["kind"] == "pref" and n["label"] == "likes:dark-mode")
    assert set(dm["surfaces"]) == {"pc:desktop", "phone:ios"}
    # dislike is flagged
    assert any(n.get("negative") for n in g["nodes"] if n["kind"] == "pref")
    # focus filter has something to filter: provenance edges exist
    assert any(e.get("prov") for e in g["edges"])
