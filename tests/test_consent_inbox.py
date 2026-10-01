"""Memory inbox: agents request consent, the owner decides (fictional data)."""
import importlib
import sys

import pytest

from fernme.service import FernService

SITE, USER = "demo.example", "dana"


def test_request_then_owner_approves(tmp_path):
    svc = FernService(db_path=str(tmp_path / "i.db"))
    out = svc.request_consent(SITE, USER, requested_by="grok-bot")
    assert out["pending"] is True and not svc.store.has_consent(SITE, USER)
    pending = svc.consent_requests()
    assert [(r["site"], r["user"], r["requested_by"]) for r in pending] == [(SITE, USER, "grok-bot")]
    svc.decide_consent_request(SITE, USER, approve=True)
    assert svc.store.has_consent(SITE, USER)
    assert svc.consent_requests() == []
    with pytest.raises(ValueError):
        svc.decide_consent_request(SITE, USER, approve=True)   # nothing pending any more


def test_owner_denies(tmp_path):
    svc = FernService(db_path=str(tmp_path / "i.db"))
    svc.request_consent(SITE, USER)
    out = svc.decide_consent_request(SITE, USER, approve=False)
    assert out["denied"] is True and not svc.store.has_consent(SITE, USER)
    assert [r["status"] for r in svc.consent_requests(status="denied")] == ["denied"]


def test_forgetting_a_user_clears_their_requests(tmp_path):
    svc = FernService(db_path=str(tmp_path / "i.db"))
    svc.request_consent(SITE, USER)
    svc.delete(SITE, USER)
    assert svc.consent_requests() == []


def test_mcp_inbox_mode_refuses_agent_confirmation(tmp_path, monkeypatch):
    pytest.importorskip("mcp")
    from fernme.api import mcp_server as server
    for var in ("FERNME_SITE", "FERNME_USER"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("FERNME_CONSENT_MODE", "inbox")
    svc = FernService(db_path=str(tmp_path / "m.db"))
    monkeypatch.setattr(server, "svc", svc)
    out = server.grant_consent(site=SITE, user=USER, confirm=True)
    assert out["pending"] is True and not svc.store.has_consent(SITE, USER)
    assert svc.consent_requests()[0]["site"] == SITE
    svc.decide_consent_request(SITE, USER, approve=True)
    assert server.grant_consent(site=SITE, user=USER)["already_granted"] is True


def test_mcp_agent_mode_request_shows_in_inbox(tmp_path, monkeypatch):
    pytest.importorskip("mcp")
    from fernme.api import mcp_server as server
    for var in ("FERNME_SITE", "FERNME_USER", "FERNME_CONSENT_MODE"):
        monkeypatch.delenv(var, raising=False)
    svc = FernService(db_path=str(tmp_path / "m.db"))
    monkeypatch.setattr(server, "svc", svc)
    server.grant_consent(site=SITE, user=USER)
    assert len(svc.consent_requests()) == 1          # owner can approve in the app too
    server.grant_consent(site=SITE, user=USER, confirm=True)
    assert svc.store.has_consent(SITE, USER) and svc.consent_requests() == []


def test_rest_inbox_endpoints(tmp_path, monkeypatch):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient
    for k in ("FERNME_API_KEY", "FERNME_CORS_ORIGINS", "FERNME_ALLOWED_HOSTS"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("FERNME_DB", str(tmp_path / "rest.db"))
    monkeypatch.delitem(sys.modules, "fernme.api.rest", raising=False)
    rest = importlib.import_module("fernme.api.rest")
    rest.svc.request_consent(SITE, USER, requested_by="openai-dots")
    client = TestClient(rest.app)
    listed = client.post("/consent-requests/list").json()
    assert listed[0]["requested_by"] == "openai-dots"
    assert client.post("/consent-requests/decide",
                       json={"site": SITE, "user": USER, "approve": True}).status_code == 200
    assert rest.svc.store.has_consent(SITE, USER)
    again = client.post("/consent-requests/decide",
                        json={"site": SITE, "user": USER, "approve": True})
    assert again.status_code == 400
