"""Graph visualization endpoint: nodes + edges for the memory graph view."""
import sys, os
import json
import pytest
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


def test_graph_assoc_floor_can_show_single_observation_tag_links():
    s = FernService(store=SQLiteStore(":memory:"))
    s.store.set_consent("demo.com", "ana", True)
    tags = ["person:dana-reyes", "org:northwind-labs", "topic:pilot-design"]
    s.observe("demo.com", "ana", "note", {"tags": tags})
    s.observe("demo.com", "ana", "note", {"tags": tags})

    strict = s.graph("demo.com", "ana", assoc_floor=2.0)
    visual = s.graph("demo.com", "ana", assoc_floor=1.0)

    assert not any(e.get("assoc") for e in strict["edges"])
    assert any(e.get("assoc") for e in visual["edges"])
    assert visual["hierarchy"]["stats"]["anchor_edges"] > strict["hierarchy"]["stats"]["anchor_edges"]


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
    assert set(g["entity_kinds"]) == {"person", "project"}
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
    daniel_works = next(e for e in relation_edges
                        if e["relation"] == "works_on"
                        and e["subject_id"] == entities["Daniel"]["entity_id"])
    assert daniel_works["fact_count"] == 2
    assert [fact["note"] for fact in daniel_works["facts"]] == [
        "Daniel reviews the fictional platform notes before demo sessions.",
        "Daniel helps Elena shape the fictional memory-journal prototype.",
    ]
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


def test_spa_graph_source_is_local_force_directed_shell():
    root = os.path.dirname(os.path.dirname(__file__))
    graph_view = open(os.path.join(root, "fernme", "web", "app", "src", "GraphView.tsx"),
                      encoding="utf-8").read()
    styles = open(os.path.join(root, "fernme", "web", "app", "src", "styles.css"),
                  encoding="utf-8").read()
    theme = open(os.path.join(root, "fernme", "web", "app", "src", "styles", "theme.css"),
                 encoding="utf-8").read()

    assert "force-graph" in graph_view
    assert "https://" not in graph_view
    assert "Search memory graph" in graph_view
    assert "FILTER_KEY" in graph_view
    assert "localStorage" in graph_view
    assert "FilterSection" in graph_view
    assert "Filter kinds" in graph_view
    assert "Select all" in graph_view and "Clear" in graph_view
    assert "CANONICAL_KINDS" in graph_view
    assert "nodePointerAreaPaint" in graph_view
    assert "nodeRadius(node) + 10" in graph_view
    assert "edgeIsKnown" in graph_view
    assert "nodeIsExplicitlyUnknown" in graph_view
    assert "knownNodeIds" in graph_view
    assert "onBackgroundClick" in graph_view
    assert "assignments" in graph_view
    assert "owner_edges" in graph_view
    assert "hierarchy_child" in graph_view
    assert "parent !== ownerLinkedAttr" in graph_view
    assert "relation: \"contains\"" in graph_view
    assert "const overviewFocus" in graph_view
    assert "child === parent" in graph_view
    assert "return overviewFocus" in graph_view
    assert "relationLabel(edge)" in graph_view
    assert "linkHoverPrecision(8)" in graph_view
    assert "onLinkHover" in graph_view
    assert "drawRelationTooltip" in graph_view
    assert "linkCanvasObjectMode" in graph_view
    assert "stripNamespace" in graph_view
    assert "drawCanvasIcon" in graph_view
    assert "canvasIconKind" in graph_view
    assert "linkDirectionalParticles" in graph_view
    assert "linkDirectionalParticleSpeed" in graph_view
    assert "graphHostRef" in graph_view
    assert 'viewMode !== "2d"' in graph_view
    assert "_destructor" in graph_view
    assert "SpatialGraphView" in graph_view
    assert "View mode" not in graph_view
    assert "Spatial" in graph_view
    assert "isOwnerNode(selected)" in graph_view
    assert "ctx.globalAlpha = focused ? 1 : 0.18" in graph_view
    assert "segmented-control" in styles
    assert "spatial-view" in styles
    assert "grid-template-columns: auto minmax(330px, 1fr) minmax(430px, 44vw)" in styles
    assert "fern-topbar-height" in styles
    assert "scrollbar-width: thin" in theme
    assert "radial-gradient(circle, var(--fern-grid-dot)" not in theme


def test_spa_shell_loads_runtime_defaults_instead_of_demo():
    root = os.path.dirname(os.path.dirname(__file__))
    store = open(os.path.join(root, "fernme", "web", "app", "src", "store.tsx"),
                 encoding="utf-8").read()
    app = open(os.path.join(root, "fernme", "web", "app", "src", "App.tsx"),
               encoding="utf-8").read()

    assert 'value="demo.com"' not in app
    assert 'value="ana"' not in app
    assert "/runtime-defaults" in store
    assert "fernme.ui.context.v1" in store
    assert "readSavedContext" in store
    assert "localStorage.setItem(CONTEXT_KEY" in store
    assert "if (!savedContext.site)" in store
    assert "showing sample" not in store + app
    assert "/graph-data" in store
    assert "assoc_floor" in store
    assert "/recall-replay" in store
    assert "RawDetails" in app
    assert "PromptCardView" in app
    assert "PayloadSummary" in app
    assert "EventSummary" in app


def test_spa_design_assets_are_source_owned_and_local():
    root = os.path.dirname(os.path.dirname(__file__))
    main = open(os.path.join(root, "fernme", "web", "app", "src", "main.tsx"),
                encoding="utf-8").read()
    app = open(os.path.join(root, "fernme", "web", "app", "src", "App.tsx"),
               encoding="utf-8").read()
    variables = open(os.path.join(root, "fernme", "web", "app", "src", "styles", "variables.css"),
                     encoding="utf-8").read()
    theme = open(os.path.join(root, "fernme", "web", "app", "src", "styles", "theme.css"),
                 encoding="utf-8").read()
    spatial = open(os.path.join(root, "fernme", "web", "app", "src", "SpatialGraphView.tsx"),
                   encoding="utf-8").read()
    logo = os.path.join(root, "fernme", "web", "app", "src", "assets", "logo.png")

    assert 'import "./styles/variables.css";' in main
    assert main.index("variables.css") < main.index("theme.css")
    assert 'import logoUrl from "./assets/logo.png";' in app
    assert "<Sprout" not in app
    assert os.path.exists(logo)
    assert "--fern-bg-root" in variables
    assert ".fern-app" in theme
    assert "https://" not in theme + spatial
    assert "3d-force-graph" in spatial
    assert "Experimental spatial view" in spatial


def test_runtime_defaults_endpoint_uses_env_without_exposing_db(monkeypatch):
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient
    import fernme.api.rest as rest

    monkeypatch.setenv("FERNME_SITE", "example.local")
    monkeypatch.setenv("FERNME_USER", "demo-user")
    monkeypatch.setenv("FERNME_DB", "redacted-db-value")

    response = TestClient(rest.app).get("/runtime-defaults")

    assert response.status_code == 200
    assert response.json() == {"site": "example.local", "user": "demo-user"}


def test_spa_ui_is_not_cached():
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient
    import fernme.api.rest as rest

    response = TestClient(rest.app).get("/ui/graph")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert 'id="root"' in response.text


def test_graph_path_redirects_to_spa():
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient
    import fernme.api.rest as rest

    response = TestClient(rest.app).get("/graph", follow_redirects=False)

    assert response.status_code in {307, 308}
    assert response.headers["location"] == "/ui/graph"


def test_recall_replay_traces_card_activation():
    s = _svc()

    replay = s.recall_replay("demo.com", "ana", ["likes:hiking"])

    assert replay["seeds"] == ["likes:hiking"]
    assert replay["card_attrs"]
    assert any(step["attr"] == "likes:hiking" for step in replay["steps"])
    assert all("activation" in step and "in_card" in step for step in replay["steps"])


def test_graph_edges_always_have_relation_type():
    s = _svc()
    g = s.graph("demo.com", "ana", assoc_floor=1.0)

    assert g["edges"]
    assert all(e.get("relation") or e.get("label") for e in g["edges"])


def test_empty_graph_response_shape_is_stable():
    s = FernService(store=SQLiteStore(":memory:"))
    s.store.set_consent("empty.local", "demo-user", True)

    g = s.graph("empty.local", "demo-user")

    assert g["nodes"] == []
    assert g["edges"] == []
    assert {"nodes", "edges", "categories", "cats", "stats", "hierarchy"} <= set(g)


def test_runtime_defaults_endpoint_infers_single_consented_context(monkeypatch):
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient
    import fernme.api.rest as rest

    monkeypatch.delenv("FERNME_SITE", raising=False)
    monkeypatch.delenv("FERNME_USER", raising=False)
    previous = rest.svc
    rest.svc = FernService(store=SQLiteStore(":memory:"))
    rest.svc.consent("personal", "demo-user", True)
    try:
        response = TestClient(rest.app).get("/runtime-defaults")
    finally:
        rest.svc = previous

    assert response.status_code == 200
    assert response.json() == {"site": "personal", "user": "demo-user"}


def test_memory_graph_is_cross_surface():
    """One owner, memories assembled across surfaces (web + pc + phone) with provenance."""
    s = FernService(store=SQLiteStore(":memory:"))
    for site, u in [("shop.com", "a1"), ("pc:desktop", "a2"), ("phone:ios", "a3")]:
        s.store.set_consent(site, u, True)
    s.observe("shop.com", "a1", "view", {"tags": ["likes:oat-milk", "!likes:dairy"]})
    s.observe("pc:desktop", "a2", "view", {"tags": ["likes:dark-mode", "topic:python"]})
    s.observe("phone:ios", "a3", "view", {"tags": ["likes:dark-mode", "time:morning"]})
    for site, u in [("shop.com", "a1"), ("pc:desktop", "a2"), ("phone:ios", "a3")]:
        s.link_identity("demo-owner", site, u)

    g = s.memory_graph("demo-owner")
    # one owner node, three surfaces
    owners = [n for n in g["nodes"] if n["kind"] == "owner"]
    assert len(owners) == 1 and owners[0]["label"] == "demo-owner"
    fams = {sf["family"] for sf in g["surfaces"]}
    assert {"web", "pc", "phone"} <= fams
    # a memory seen on two surfaces carries both as provenance
    dm = next(n for n in g["nodes"] if n["kind"] == "pref" and n["label"] == "likes:dark-mode")
    assert set(dm["surfaces"]) == {"pc:desktop", "phone:ios"}
    # dislike is flagged
    assert any(n.get("negative") for n in g["nodes"] if n["kind"] == "pref")
    # focus filter has something to filter: provenance edges exist
    assert any(e.get("prov") for e in g["edges"])
