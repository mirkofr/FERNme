"""Regression tests for the adversarial review of remote MCP + engine changes:
remote agents cannot read server files or approve their own suggestions, the
consent inbox cannot be bypassed or spammed, slot recency ignores untimed
values, outcomes are bounded, exports are unique and clean, and decay does not
resurrect deleted users. Fictional data and temporary databases only."""
import json

import pytest

pytest.importorskip("mcp")

from fernme.api import mcp_server as server
from fernme.api.remote import REQUEST_CLIENT
from fernme.service import FernService

SITE, USER = "demo.example", "dana"


@pytest.fixture()
def svc(tmp_path, monkeypatch):
    for var in ("FERNME_SITE", "FERNME_USER", "FERNME_ALLOW_OTHER_PROFILES",
                "FERNME_CONSENT_MODE", "FERNME_REMOTE_CONSENT"):
        monkeypatch.delenv(var, raising=False)
    service = FernService(db_path=str(tmp_path / "hardening.db"))
    monkeypatch.setattr(server, "svc", service)
    return service


@pytest.fixture()
def as_remote():
    token = REQUEST_CLIENT.set((SITE, USER, "grok-bot"))
    yield
    REQUEST_CLIENT.reset(token)


def _tool_names(srv):
    import anyio
    return {t.name for t in anyio.run(srv.list_tools)}


# ---- 1. remote agents and server files -------------------------------------

def test_remote_server_does_not_list_file_reading_or_approval_tools():
    local = _tool_names(server.build_server({"core", "documents", "photos"}))
    remote = _tool_names(server.build_remote_server({"core", "documents", "photos"}))
    assert server.REMOTE_BLOCKED_TOOLS <= local
    assert not (server.REMOTE_BLOCKED_TOOLS & remote)
    assert {"remember", "recall_card", "reject_canonicalization_suggestion"} <= remote


def test_remote_calls_to_local_only_tools_are_refused(svc, tmp_path, as_remote):
    secret = tmp_path / "vault"
    secret.mkdir()
    (secret / "note.md").write_text("Fictional private note.")
    with pytest.raises(server.RemoteToolBlockedError):
        server.import_obsidian(str(secret), dry_run=False)
    with pytest.raises(server.RemoteToolBlockedError):
        server.import_document(str(secret / "note.md"), confirm=True)
    with pytest.raises(server.RemoteToolBlockedError):
        server.accept_canonicalization_suggestion("any-id")


def test_local_agents_keep_the_file_tools(svc, tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "note.md").write_text("A fictional note.")
    server.grant_consent(site=SITE, user=USER, confirm=True)
    out = server.import_obsidian(str(vault), site=SITE, user=USER)
    assert out.get("dry_run", True) is True


# ---- 2. document import respects the consent inbox -------------------------

def test_confirmed_document_import_files_a_request_in_inbox_mode(svc, tmp_path,
                                                                 monkeypatch):
    monkeypatch.setenv("FERNME_CONSENT_MODE", "inbox")
    doc = tmp_path / "doc.md"
    doc.write_text("A fictional document.")
    out = server._import_document(str(doc), SITE, USER, confirm=True)
    assert out["pending"] is True and out["ok"] is False
    assert svc.store.has_consent(SITE, USER) is False
    assert svc.consent_requests()[0]["site"] == SITE


# ---- suspected: re-requesting after a denial -------------------------------

def test_denied_request_stays_denied_in_inbox_mode(svc, monkeypatch):
    monkeypatch.setenv("FERNME_CONSENT_MODE", "inbox")
    assert server.grant_consent(site=SITE, user=USER)["pending"] is True
    svc.decide_consent_request(SITE, USER, approve=False)
    again = server.grant_consent(site=SITE, user=USER)
    assert again["denied"] is True
    assert svc.consent_requests() == []            # nothing re-queued


def test_agent_mode_user_can_say_yes_after_an_earlier_denial(svc):
    server.grant_consent(site=SITE, user=USER)
    svc.decide_consent_request(SITE, USER, approve=False)
    out = server.grant_consent(site=SITE, user=USER, confirm=True)
    assert out["consent"] is True


# ---- 3. slot recency with untimed values -----------------------------------

def test_untimed_correction_is_not_hidden_behind_a_timed_old_value(svc):
    # Old value written with wall-clock times (e.g. REST), a full card of other
    # memories, then a repeated correction over MCP, whose ts defaults to 0.
    svc.consent(SITE, USER, True)
    others = [f"pref:x{i}" for i in range(9)]
    for t in (1_700_000_000.0, 1_700_000_100.0):
        svc.observe(SITE, USER, "chat", {"tags": ["city:harbor-town"] + others}, ts=t)
    for _ in range(3):
        server.remember(site=SITE, user=USER, tags=["city:river-city"])
    shown = [link["attr"] for link in svc.card(SITE, USER)["links"]]
    assert "city:river-city" in shown          # previously pushed behind every memory


# ---- 4. record_outcome bounds ----------------------------------------------

def test_outcome_weight_is_clamped_and_overrides_are_left_alone(svc):
    svc.consent(SITE, USER, True)
    svc.observe(SITE, USER, "chat", {"tags": ["pref:tea", "pref:jazz"]}, ts=1.0)
    svc.edit(SITE, USER, "pref:jazz", 7.0)
    svc.record_outcome(SITE, USER, False, attrs=["pref:tea", "pref:jazz"], weight=-50)
    svc.record_outcome(SITE, USER, True, attrs=["pref:tea"], weight=1e9)
    edges = svc.store.load_user(SITE, USER).edges
    assert 0.0 <= edges["pref:tea"].weight <= svc.cfg.w_max
    assert edges["pref:jazz"].weight == 7.0
    with pytest.raises(ValueError):
        svc.record_outcome(SITE, USER, True, attrs=["pref:tea"], weight=float("nan"))


def test_outcome_without_attrs_uses_the_last_real_event(svc):
    svc.consent(SITE, USER, True)
    svc.observe(SITE, USER, "chat", {"tags": ["pref:tea"]}, ts=0.0)
    svc.observe(SITE, USER, "chat", {"tags": ["pref:coffee"]}, ts=0.0)
    first = svc.record_outcome(SITE, USER, True)
    second = svc.record_outcome(SITE, USER, True)     # must skip the outcome event
    assert first["attrs"] == ["pref:coffee"] == second["attrs"]


# ---- 5. export files ---------------------------------------------------------

def test_exports_in_the_same_second_do_not_collide(svc):
    svc.consent(SITE, USER, True)
    svc.observe(SITE, USER, "chat", {"tags": ["pref:tea"]}, ts=1.0)
    a, b = svc.export_to_file(SITE, USER), svc.export_to_file(SITE, USER)
    assert a["path"] != b["path"]


def test_remote_export_returns_only_the_file_name(svc, as_remote):
    svc.consent(SITE, USER, True)
    svc.observe(SITE, USER, "chat", {"tags": ["pref:tea"]}, ts=1.0)
    out = server.export_memory()
    assert "/" not in out["path"] and "\\" not in out["path"]
    assert out["path"].endswith(".json")


# ---- 6. decay bookkeeping ----------------------------------------------------

def test_decay_does_not_recreate_a_deleted_user(svc):
    svc.consent(SITE, USER, True)
    svc.observe(SITE, USER, "chat", {"tags": ["pref:tea"]}, ts=1.0)
    svc.delete(SITE, USER)
    svc.decay(SITE, USER, now=100.0)
    ug = svc.store.load_user(SITE, USER)
    assert ug.edges == {} and ug.numeric == {}


def test_export_hides_internal_bookkeeping(svc):
    svc.consent(SITE, USER, True)
    for t in (1.0, 2.0, 3.0):
        svc.observe(SITE, USER, "chat", {"tags": ["pref:tea"]}, ts=t)
    svc.decay(SITE, USER, now=4.0)
    assert "_decay_clock" in svc.store.load_user(SITE, USER).numeric
    data = svc.export(SITE, USER)
    assert not any(str(k).startswith("_") for k in data["numeric"])
    json.dumps(data, default=str)
