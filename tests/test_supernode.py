"""User-owned supernode tests. Run: pytest -q"""
import sys, os, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from fernme.service import FernService
from fernme.supernode import is_sensitive


def _svc():
    fd, p = tempfile.mkstemp(suffix=".db"); os.close(fd); os.remove(p)
    return FernService(p)


def _seed(svc, site, user, tags_list):
    svc.consent(site, user, True)
    for ts, tags in enumerate(tags_list):
        svc.observe(site, user, "event", {"tags": tags}, ts=ts)


def test_assembly_merges_with_provenance():
    svc = _svc()
    _seed(svc, "grocery", "g1", [["vegetarian"], ["vegetarian"], ["dairy"]])
    _seed(svc, "travel", "t1", [["flight:firstclass"], ["flight:firstclass"]])
    svc.link_identity("p:x", "grocery", "g1")
    svc.link_identity("p:x", "travel", "t1")
    card = svc.supernode_card("p:x")
    attrs = {l["attr"]: l for l in card["links"]}
    assert "vegetarian" in attrs and "flight:firstclass" in attrs
    assert attrs["vegetarian"]["from"] == ["grocery"]
    assert attrs["flight:firstclass"]["from"] == ["travel"]


def test_default_deny_cross_site():
    svc = _svc()
    _seed(svc, "grocery", "g1", [["vegetarian"], ["vegetarian"]])
    _seed(svc, "travel", "t1", [["flight:firstclass"], ["flight:firstclass"]])
    svc.link_identity("p:x", "grocery", "g1"); svc.link_identity("p:x", "travel", "t1")
    # grocery must NOT see travel's brick with no sharing policy
    g = svc.view_for_site("p:x", "grocery")
    seen = {l["attr"] for l in g["links"]}
    assert "vegetarian" in seen and "flight:firstclass" not in seen


def test_opt_in_sharing():
    svc = _svc()
    _seed(svc, "grocery", "g1", [["allergy:almond"], ["allergy:almond"]])
    svc.link_identity("p:x", "grocery", "g1")
    svc.consent("mealkit", "m1", True); svc.link_identity("p:x", "mealkit", "m1")
    assert svc.view_for_site("p:x", "mealkit")["links"] == []      # nothing by default
    svc.set_share("p:x", "mealkit", "allergy", True)
    seen = {l["attr"] for l in svc.view_for_site("p:x", "mealkit")["links"]}
    assert "allergy:almond" in seen                                # now shared


def test_sensitive_detection():
    assert is_sensitive("allergy:almond")
    assert is_sensitive("dating:blonde")
    assert not is_sensitive("vegetarian")
    assert not is_sensitive("hotel:5star")


def test_unlink_removes_contribution():
    svc = _svc()
    _seed(svc, "dating", "d1", [["dating:blonde"], ["dating:blonde"]])
    svc.link_identity("p:x", "dating", "d1")
    assert any("dating" in l["attr"] for l in svc.supernode_card("p:x")["links"])
    svc.unlink_identity("p:x", "dating", "d1")
    assert not any("dating" in l["attr"] for l in svc.supernode_card("p:x")["links"])


def test_owner_sees_sensitive_flag():
    svc = _svc()
    _seed(svc, "grocery", "g1", [["allergy:almond"], ["allergy:almond"]])
    svc.link_identity("p:x", "grocery", "g1")
    card = svc.supernode_card("p:x")
    almond = [l for l in card["links"] if l["attr"] == "allergy:almond"][0]
    assert almond["sensitive"] is True
