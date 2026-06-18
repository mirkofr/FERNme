"""Verifiable data ownership (#4): tamper-evident log + cascading unlearning.
Run: pytest -q tests/test_audit.py"""
import sys, os, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from fernme.service import FernService


def _svc():
    fd, p = tempfile.mkstemp(suffix=".db"); os.close(fd); os.remove(p)
    return FernService(p)


def test_audit_records_and_verifies():
    svc = _svc()
    svc.consent("s", "u", True)
    svc.observe("s", "u", "visit", {"tags": ["morning_pref"]})
    svc.edit("s", "u", "morning_pref", 9)
    log = svc.audit_log("s", "u")
    assert [e["action"] for e in log] == ["consent", "observe", "edit"]
    assert svc.verify_audit("s", "u") == {"ok": True, "broken_at_seq": None}


def test_tampering_is_detected():
    svc = _svc()
    svc.consent("s", "u", True)
    svc.observe("s", "u", "visit", {"tags": ["x"]})
    svc.observe("s", "u", "visit", {"tags": ["y"]})
    # secretly alter an audit entry's detail in the DB
    svc.store._conn.execute(
        "UPDATE audit SET detail=? WHERE site='s' AND user='u' AND seq=1",
        ('{"type": "TAMPERED", "n_attrs": 99}',))
    svc.store._conn.commit()
    res = svc.verify_audit("s", "u")
    assert res["ok"] is False and res["broken_at_seq"] == 1


def test_forget_everywhere_unlearns_from_prior():
    svc = _svc()
    # 5 users strongly early_riser, 1 weak outlier -> prior mean pulled down
    for i in range(5):
        svc.consent("clinic", f"u{i}", True)
        for _ in range(5):
            svc.observe("clinic", f"u{i}", "visit", {"tags": ["early_riser"]})
    svc.consent("clinic", "outlier", True)
    svc.observe("clinic", "outlier", "visit", {"tags": ["early_riser"]})   # 1 obs -> low weight
    svc.prior_refresh("clinic")
    before = svc.store.load_prior("clinic").mean("early_riser")
    svc.forget_everywhere("clinic", "outlier")        # delete + cascading unlearn
    after = svc.store.load_prior("clinic").mean("early_riser")
    assert after > before                             # outlier's drag is gone
    assert svc.store.load_user("clinic", "outlier").n_edges() == 0   # fully wiped
