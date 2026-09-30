"""Regression tests for the 2026-09-30 privacy review (synthetic data only)."""
import json
import os

from fernme import install_key
from fernme.audit import GENESIS, entry_hash
from fernme.service import FernService

SITE = "privacy.example"


def _population(svc, n=6, extra=None):
    for i in range(n):
        u = f"u{i}"
        svc.consent(SITE, u, True)
        tags = ["topic:hiking"] + (extra.get(u, []) if extra else [])
        for _ in range(3):
            svc.observe(SITE, u, "chat", {"tags": tags})
    svc.prior_refresh(SITE)


def _prior_attrs(svc):
    return {r["attr"] for r in svc.store._conn.execute(
        "SELECT attr FROM prior_node WHERE site=?", (SITE,))}


def test_single_user_trait_never_reaches_a_newcomer():
    svc = FernService(db_path=":memory:")
    _population(svc, extra={"u0": ["pref:rare-gin"]})
    svc.consent(SITE, "newcomer", True)
    wire = svc.card(SITE, "newcomer")["wire"]
    assert "topic:hiking" in wire              # common trait still helps cold start
    assert "pref:rare-gin" not in wire         # k-anonymity: one holder is not enough


def test_common_sensitive_trait_is_not_seeded():
    svc = FernService(db_path=":memory:")
    _population(svc, extra={f"u{i}": ["health:asthma"] for i in range(6)})
    svc.consent(SITE, "newcomer", True)
    assert "health:asthma" not in svc.card(SITE, "newcomer")["wire"]


def test_forget_and_delete_remove_unique_traits_from_the_prior():
    for forget in ("forget_everywhere", "delete", "withdraw"):
        svc = FernService(db_path=":memory:")
        _population(svc, extra={"u0": ["pref:rare-gin"]})
        assert "pref:rare-gin" in _prior_attrs(svc)
        if forget == "forget_everywhere":
            svc.forget_everywhere(SITE, "u0")
        elif forget == "delete":
            svc.delete(SITE, "u0")
        else:
            svc.consent(SITE, "u0", False)
        assert "pref:rare-gin" not in _prior_attrs(svc), forget


def test_delete_removes_identity_links_and_orphaned_share_rules():
    svc = FernService(db_path=":memory:")
    svc.consent(SITE, "u", True)
    svc.observe(SITE, "u", "chat", {"tags": ["topic:hiking"]})
    svc.link_identity("person:p", SITE, "u")
    svc.set_share("person:p", "other.example", "topic", True)
    svc.forget_everywhere(SITE, "u")
    assert svc.store.list_identities("person:p") == []
    assert svc.store.get_shares("person:p", "other.example") == {}


def test_released_prior_is_stable_and_noise_is_not_the_public_seed():
    svc = FernService(db_path=":memory:")
    _population(svc, n=8)
    svc.consent(SITE, "a", True)
    svc.consent(SITE, "b", True)
    assert svc.card(SITE, "a")["wire"].split("|")[1] == svc.card(SITE, "b")["wire"].split("|")[1]
    secret_noise = svc.private_prior(SITE).mean("topic:hiking")
    public_noise = svc.private_prior(SITE, seed=0).mean("topic:hiking")
    assert secret_noise != public_noise


def test_new_database_gets_its_own_audit_key(tmp_path):
    db = tmp_path / "m.db"
    svc = FernService(db_path=str(db))
    svc.consent(SITE, "u", True)
    assert (tmp_path / "m.db.key").is_file()
    assert svc.audit_key != install_key.LEGACY_AUDIT_KEY
    assert svc.verify_audit(SITE, "u") == {"ok": True, "broken_at_seq": None}

    # an attacker who knows the old public constant can no longer forge history
    rows = svc.store.read_audit(SITE, "u")
    forged = entry_hash(install_key.LEGACY_AUDIT_KEY, GENESIS, 0, rows[0]["ts"],
                        "consent", {"granted": False})
    svc.store._conn.execute(
        "UPDATE audit SET detail=?, hash=? WHERE site=? AND user=? AND seq=0",
        (json.dumps({"granted": False}), forged, SITE, "u"))
    svc.store._conn.commit()
    assert svc.verify_audit(SITE, "u")["ok"] is False

    # a second process on the same database shares the key
    assert FernService(db_path=str(db)).verify_audit(SITE, "other")["ok"] is True
    assert FernService(db_path=str(db)).audit_key == svc.audit_key


def test_existing_database_keeps_verifying_with_legacy_key(tmp_path):
    db = tmp_path / "old.db"
    svc = FernService(db_path=str(db))
    os.remove(str(db) + ".key")
    # simulate a pre-fix database: chain signed with the legacy constant
    svc.store._conn.execute("DELETE FROM audit")
    svc.store._conn.commit()
    svc.store.append_audit(SITE, "u", 0.0, "consent", {"granted": True},
                           install_key.LEGACY_AUDIT_KEY)
    reopened = FernService(db_path=str(db))
    assert reopened.audit_key == install_key.LEGACY_AUDIT_KEY
    assert reopened.verify_audit(SITE, "u") == {
        "ok": True, "broken_at_seq": None, "legacy_key": True}
    assert "audit=legacy" in (tmp_path / "old.db.key").read_text()
    assert FernService(db_path=str(db)).audit_key_legacy is True


def test_edit_audit_entry_does_not_store_the_memory_name():
    svc = FernService(db_path=":memory:")
    svc.consent(SITE, "u", True)
    svc.edit(SITE, "u", "health:asthma", 0)
    details = [e["detail"] for e in svc.audit_log(SITE, "u") if e["action"] == "edit"]
    assert details and "health:asthma" not in json.dumps(details)
    assert details[0]["attr_ref"] == svc._audit_ref("health:asthma")


def test_sharing_a_plain_category_does_not_leak_sensitive_members():
    svc = FernService(db_path=":memory:")
    svc.consent("a.example", "u", True)
    for _ in range(2):
        svc.observe("a.example", "u", "chat",
                    {"tags": ["topic:hiking", "topic:mental_health_support"]})
    svc.link_identity("person:p", "a.example", "u")
    svc.consent("b.example", "u2", True)
    svc.link_identity("person:p", "b.example", "u2")
    svc.set_share("person:p", "b.example", "topic", True)
    seen = {l["attr"] for l in svc.view_for_site("person:p", "b.example")["links"]}
    assert "topic:hiking" in seen and "topic:mental_health_support" not in seen
    svc.set_share("person:p", "b.example", "sensitive:topic", True)
    seen = {l["attr"] for l in svc.view_for_site("person:p", "b.example")["links"]}
    assert "topic:mental_health_support" in seen


def test_concurrent_key_file_creation_never_sees_an_empty_file(tmp_path):
    import threading
    from fernme.store.sqlite_store import SQLiteStore
    db = tmp_path / "race.db"
    store = SQLiteStore(str(db))
    results, errors = [], []

    def worker():
        try:
            for _ in range(20):
                results.append(install_key.resolve(store)[0])
        except Exception as exc:
            errors.append(exc)
    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    assert len(set(results)) == 1


def test_audit_ref_is_keyed_by_secret_even_on_legacy_databases(tmp_path):
    db = tmp_path / "old.db"
    svc = FernService(db_path=str(db))
    os.remove(str(db) + ".key")
    svc.store.append_audit(SITE, "u", 0.0, "consent", {"granted": True},
                           install_key.LEGACY_AUDIT_KEY)
    legacy = FernService(db_path=str(db))
    assert legacy.audit_key_legacy is True
    import hashlib, hmac
    public = hmac.new(install_key.LEGACY_AUDIT_KEY, b"health:asthma",
                      hashlib.sha256).hexdigest()[:24]
    assert legacy._audit_ref("health:asthma") != public


def test_existing_memory_names_stay_editable():
    svc = FernService(db_path=":memory:")
    svc.consent(SITE, "u", True)
    svc.set_catalog({"sku1": ["size:9.5"]})
    svc.observe(SITE, "u", "purchase", {"item_id": "sku1"})
    assert "size:9.5" in svc.store.load_user(SITE, "u").edges
    assert svc.edit(SITE, "u", "size:9.5", 0)["attr"] == "size:9.5"
