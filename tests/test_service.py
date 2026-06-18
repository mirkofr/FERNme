"""v1 service + persistence tests. Run: pytest -q"""
import sys, os, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import pytest
from fernme.service import FernService, ConsentError


def _svc():
    fd, path = tempfile.mkstemp(suffix=".db"); os.close(fd); os.remove(path)
    return FernService(path), path


def test_consent_gate_blocks_writes():
    svc, _ = _svc()
    with pytest.raises(ConsentError):
        svc.observe("s", "u", "purchase", {"tags": ["organic"]})


def test_persistence_across_instances():
    svc, path = _svc()
    svc.consent("s", "u", True)
    for w in range(5):
        svc.observe("s", "u", "purchase", {"tags": ["organic"]}, ts=w)
    # brand-new service object, same db file -> memory must survive
    svc2 = FernService(path)
    card = svc2.card("s", "u", now=10)
    assert "organic" in card["wire"]
    assert svc2.store.load_user("s", "u").edges["organic"].weight > 1.0


def test_tenant_isolation():
    svc, _ = _svc()
    svc.consent("s", "a", True); svc.consent("s", "b", True)
    for _ in range(3):
        svc.observe("s", "a", "purchase", {"tags": ["vegan"]})
    assert "vegan" in svc.card("s", "a")["wire"]
    assert "vegan" not in svc.card("s", "b")["wire"]   # b never sees a's data


def test_cabinet_recall_specifics():
    svc, _ = _svc()
    svc.consent("s", "u", True)
    svc.observe("s", "u", "booking", {"tags": ["cardiology"], "doctor": "Dr. Lee", "time": "6pm"})
    hits = svc.recall("s", "u", contains="Dr. Lee")
    assert hits and hits[0]["payload"]["doctor"] == "Dr. Lee"


def test_override_locked_and_persisted():
    svc, path = _svc()
    svc.consent("s", "u", True)
    svc.observe("s", "u", "purchase", {"tags": ["dairy"]})
    svc.edit("s", "u", "dairy", 0)
    e = FernService(path).store.load_user("s", "u").edges["dairy"]
    assert e.source == "override" and e.weight == 0.0


def test_delete_removes_everything():
    svc, _ = _svc()
    svc.consent("s", "u", True)
    svc.observe("s", "u", "purchase", {"tags": ["organic"]})
    svc.delete("s", "u")
    assert svc.store.load_user("s", "u").n_edges() == 0
    with pytest.raises(ConsentError):       # consent purged too
        svc.card("s", "u")


def test_cold_start_from_prior():
    svc, _ = _svc()
    # build a prior from several organic-leaning users
    for i in range(4):
        svc.consent("s", f"u{i}", True)
        for _ in range(4):
            svc.observe("s", f"u{i}", "purchase", {"tags": ["organic"]})
    svc.prior_refresh("s")
    svc.consent("s", "newcomer", True)
    card = svc.card("s", "newcomer", now=1)   # empty profile -> should borrow prior
    assert "organic" in card["wire"]
    assert any(not l["known"] for l in card["links"])  # borrowed = guessed
