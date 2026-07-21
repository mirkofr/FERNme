"""PostgresStore against a REAL Postgres (rootless pgserver). Skips if pgserver
isn't installed. Run: pytest -q tests/test_postgres.py"""
import sys, os, tempfile, shutil
import uuid
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import pytest
from dataclasses import replace

pgserver = pytest.importorskip("pgserver")
from fernme.service import FernService
from fernme.config import DEFAULT
from fernme.store.postgres_store import PostgresStore


@pytest.fixture(scope="module")
def pg():
    d = tempfile.mkdtemp(prefix="pgdata_")
    srv = pgserver.get_server(d)
    yield srv.get_uri()
    srv.cleanup(); shutil.rmtree(d, ignore_errors=True)


def test_full_lifecycle_on_postgres(pg):
    svc = FernService(store=PostgresStore(pg))
    svc.consent("shop", "demo-user", True)
    for w in range(5):
        svc.observe("shop", "demo-user", "purchase", {"tags": ["organic", "mid_range"]}, ts=w)
    svc.set_numeric("shop", "demo-user", "restock_cadence_days", 7)
    card = svc.card("shop", "demo-user", now=40)
    assert "organic" in card["wire"] and "restock_cadence_days" in card["wire"]
    assert len(svc.recall("shop", "demo-user", type="purchase")) == 5
    # glass-box override persists in PG
    svc.edit("shop", "demo-user", "dairy", 0)
    assert FernService(store=PostgresStore(pg)).store.load_user("shop", "demo-user").edges["dairy"].source == "override"


def test_tenant_isolation_on_postgres(pg):
    svc = FernService(store=PostgresStore(pg))
    svc.consent("shop", "a", True); svc.consent("shop", "b", True)
    for _ in range(3):
        svc.observe("shop", "a", "purchase", {"tags": ["vegan"]})
    assert "vegan" in svc.card("shop", "a")["wire"]
    assert "vegan" not in svc.card("shop", "b")["wire"]


def test_supernode_on_postgres(pg):
    svc = FernService(store=PostgresStore(pg))
    for site, u, tags in [("grocery", "g1", ["vegetarian"]), ("travel", "t1", ["flight:firstclass"])]:
        svc.consent(site, u, True)
        for _ in range(2):
            svc.observe(site, u, "event", {"tags": tags})
        svc.link_identity("p:joe", site, u)
    card = svc.supernode_card("p:joe")
    attrs = {l["attr"] for l in card["links"]}
    assert "vegetarian" in attrs and "flight:firstclass" in attrs
    # default-deny scoped view
    seen = {l["attr"] for l in svc.view_for_site("p:joe", "grocery")["links"]}
    assert "vegetarian" in seen and "flight:firstclass" not in seen


def test_delete_on_postgres(pg):
    svc = FernService(store=PostgresStore(pg))
    svc.consent("shop", "z", True)
    svc.observe("shop", "z", "purchase", {"tags": ["organic"]})
    svc.delete("shop", "z")
    assert svc.store.load_user("shop", "z").n_edges() == 0


def test_media_metadata_lifecycle_on_postgres(pg, tmp_path):
    Image = pytest.importorskip("PIL.Image")
    from io import BytesIO

    output = BytesIO()
    Image.new("RGB", (8, 8), "orange").save(output, format="PNG")
    svc = FernService(
        store=PostgresStore(pg),
        cfg=replace(DEFAULT, media_enabled=True),
        media_root=str(tmp_path / "postgres-assets"),
    )
    svc.consent("media-demo", "elena", True)

    stored = svc.observe_asset(
        "media-demo", "elena", output.getvalue(), ["topic:orange"], now=1.0)

    assert svc.get_asset("media-demo", "elena", stored["id"])["mime"] == "image/png"
    assert len(svc.store.list_assets("media-demo", "elena")) == 1
    assert svc.forget_asset("media-demo", "elena", stored["id"])["forgotten"] is True
    assert svc.store.list_assets("media-demo", "elena") == []


def test_canonicalization_suggestions_on_postgres(pg):
    svc = FernService(store=PostgresStore(pg))
    svc.consent("demo", "alex", True)
    svc.observe("demo", "alex", "note", {"tags": ["person:dana-reyes"]})
    svc.observe("demo", "alex", "note", {"tags": ["person:danareyes"]})

    rows = svc.list_suggestions("demo", "alex", now=1.0)
    rejected = svc.reject_suggestion("demo", "alex", rows[0]["suggestion_id"], ts=2.0)

    assert rows[0]["kind"] == "alias-merge"
    assert rejected["status"] == "rejected"
    assert svc.list_suggestions("demo", "alex", now=3.0) == []


def test_entity_rekind_suggestion_on_postgres(pg):
    svc = FernService(store=PostgresStore(pg))
    svc.consent("demo", "casey", True)
    entity_id = str(uuid.uuid4())
    svc.store.create_entity(entity_id, "demo", "casey", "workflow", "Synthetic Workflow", 1.0)

    row = next(r for r in svc.list_suggestions("demo", "casey", now=2.0)
               if r["kind"] == "entity-rekind")
    accepted = svc.accept_suggestion("demo", "casey", row["suggestion_id"], ts=3.0)

    assert row["payload"]["old_kind"] == "workflow"
    assert row["payload"]["proposed_kind"] == "other"
    assert accepted["status"] == "accepted"
    assert svc.store.get_entity("demo", "casey", entity_id)["kind"] == "other"


def test_assoc_k_suppression_on_postgres(pg):
    svc = FernService(store=PostgresStore(pg))
    for user in ("alex", "bea", "cora"):
        svc.consent("privacy", user, True)
    svc.observe("privacy", "alex", "note", {"tags": ["topic:rain", "pref:mint"]}, ts=1.0)

    pair = ("pref:mint", "topic:rain")
    assert pair in svc.store.load_assoc("privacy", user="alex", min_users=2).edges
    assert pair not in svc.store.load_assoc("privacy", user="bea", min_users=2).edges

    svc.observe("privacy", "bea", "note", {"tags": ["topic:rain", "pref:mint"]}, ts=2.0)

    assert pair in svc.store.load_assoc("privacy", user="cora", min_users=2).edges
