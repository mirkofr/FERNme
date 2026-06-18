"""Sign-in -> supernode linking (mock IdP). Run: pytest -q tests/test_auth.py"""
import sys, os, tempfile, time
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import pytest
from fernme.service import FernService
from fernme.auth import MockProvider, sign_in_and_link, person_id_for, AuthError


def _svc():
    fd, p = tempfile.mkstemp(suffix=".db"); os.close(fd); os.remove(p)
    return FernService(p)


def _seed(svc, site, user, tags):
    svc.consent(site, user, True)
    for _ in range(2):
        svc.observe(site, user, "event", {"tags": tags})


def test_signin_links_same_person_across_sites():
    svc, idp = _svc(), MockProvider()
    _seed(svc, "grocery", "g1", ["vegetarian"])
    _seed(svc, "travel", "t1", ["flight:firstclass"])
    tok = idp.issue("user-123", "joe@example.com")        # one identity...
    sign_in_and_link(svc, idp, tok, "grocery", "g1")       # ...signs in on two sites
    out = sign_in_and_link(svc, idp, tok, "travel", "t1")
    person = out["person"]
    attrs = {l["attr"] for l in svc.supernode_card(person)["links"]}
    assert "vegetarian" in attrs and "flight:firstclass" in attrs   # supernode assembled


def test_forged_token_rejected():
    svc, idp = _svc(), MockProvider()
    tok = idp.issue("user-123")
    forged = tok[:-2] + ("aa" if not tok.endswith("aa") else "bb")  # tamper signature
    with pytest.raises(AuthError):
        sign_in_and_link(svc, idp, forged, "grocery", "g1")


def test_expired_token_rejected():
    svc, idp = _svc(), MockProvider()
    tok = idp.issue("user-123", ttl=-1)                    # already expired
    with pytest.raises(AuthError):
        sign_in_and_link(svc, idp, tok, "grocery", "g1")


def test_untrusted_issuer_rejected():
    svc = _svc()
    real, attacker = MockProvider(issuer="mock-idp"), MockProvider(issuer="evil", secret=b"x")
    tok = attacker.issue("user-123")
    with pytest.raises(AuthError):
        sign_in_and_link(svc, real, tok, "grocery", "g1")


def test_person_id_stable_and_opaque():
    idp = MockProvider()
    a = person_id_for(idp.verify(idp.issue("u1")))
    b = person_id_for(idp.verify(idp.issue("u1")))
    c = person_id_for(idp.verify(idp.issue("u2")))
    assert a == b and a != c and a.startswith("person:")
    assert "u1" not in a                                   # opaque, not guessable from id
