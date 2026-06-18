"""PostgresStore against a REAL Postgres (rootless pgserver). Skips if pgserver
isn't installed. Run: pytest -q tests/test_postgres.py"""
import sys, os, tempfile, shutil
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import pytest

pgserver = pytest.importorskip("pgserver")
from fernme.service import FernService
from fernme.store.postgres_store import PostgresStore


@pytest.fixture(scope="module")
def pg():
    d = tempfile.mkdtemp(prefix="pgdata_")
    srv = pgserver.get_server(d)
    yield srv.get_uri()
    srv.cleanup(); shutil.rmtree(d, ignore_errors=True)


def test_full_lifecycle_on_postgres(pg):
    svc = FernService(store=PostgresStore(pg))
    svc.consent("shop", "mirko", True)
    for w in range(5):
        svc.observe("shop", "mirko", "purchase", {"tags": ["organic", "mid_range"]}, ts=w)
    svc.set_numeric("shop", "mirko", "restock_cadence_days", 7)
    card = svc.card("shop", "mirko", now=40)
    assert "organic" in card["wire"] and "restock_cadence_days" in card["wire"]
    assert len(svc.recall("shop", "mirko", type="purchase")) == 5
    # glass-box override persists in PG
    svc.edit("shop", "mirko", "dairy", 0)
    assert FernService(store=PostgresStore(pg)).store.load_user("shop", "mirko").edges["dairy"].source == "override"


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
