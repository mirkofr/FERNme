"""Agent-facing safety of the MCP tools: ask-first consent, profile lock,
Obsidian preview by default. Fictional data and temporary databases only."""
import importlib.util

import pytest

pytest.importorskip("mcp")

from fernme.api import mcp_server as server
from fernme.service import FernService


@pytest.fixture()
def svc(tmp_path, monkeypatch):
    for var in ("FERNME_SITE", "FERNME_USER", "FERNME_ALLOW_OTHER_PROFILES"):
        monkeypatch.delenv(var, raising=False)
    service = FernService(db_path=str(tmp_path / "agent.db"))
    monkeypatch.setattr(server, "svc", service)
    return service


def test_consent_needs_a_second_confirmed_call(svc):
    first = server.grant_consent(site="demo.example", user="dana")
    assert first["needs_user_confirmation"] is True
    assert "May FERNme remember" in first["question"]
    assert svc.store.has_consent("demo.example", "dana") is False
    with pytest.raises(Exception):
        server.remember(site="demo.example", user="dana", tags=["pref:tea"])

    second = server.grant_consent(site="demo.example", user="dana", confirm=True)
    assert second["consent"] is True
    assert svc.store.has_consent("demo.example", "dana") is True
    again = server.grant_consent(site="demo.example", user="dana")
    assert again["already_granted"] is True


def test_withdrawing_consent_is_immediate(svc):
    server.grant_consent(site="demo.example", user="dana", confirm=True)
    server.remember(site="demo.example", user="dana", tags=["pref:tea"])
    out = server.grant_consent(site="demo.example", user="dana", granted=False)
    assert out["consent"] is False
    assert svc.store.load_user("demo.example", "dana").edges == {}


def test_configured_profile_blocks_other_profiles(svc, monkeypatch):
    monkeypatch.setenv("FERNME_SITE", "home")
    monkeypatch.setenv("FERNME_USER", "owner")
    server.grant_consent(site="home", user="owner", confirm=True)
    server.remember(site="home", user="owner", tags=["pref:tea"])

    with pytest.raises(server.ProfileLockedError):
        server.recall_card(site="home", user="someone-else")
    with pytest.raises(server.ProfileLockedError):
        server.grant_consent(site="other.example", user="owner", confirm=True)
    with pytest.raises(server.ProfileLockedError):
        server.forget_me(site="home", user="someone-else")
    assert "pref:tea" in server.recall_card(site="home", user="owner")["wire"]


def test_no_profile_configured_keeps_free_choice(svc):
    server.grant_consent(site="a.example", user="x", confirm=True)
    server.grant_consent(site="b.example", user="y", confirm=True)
    assert svc.store.has_consent("b.example", "y")


def test_lock_can_be_turned_off_explicitly(svc, monkeypatch):
    monkeypatch.setenv("FERNME_SITE", "home")
    monkeypatch.setenv("FERNME_ALLOW_OTHER_PROFILES", "true")
    server.grant_consent(site="elsewhere", user="x", confirm=True)
    assert svc.store.has_consent("elsewhere", "x")


def test_obsidian_import_previews_by_default(svc, tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "note.md").write_text("---\ntags: [pref/tea]\n---\nA fictional note.",
                                   encoding="utf-8")
    server.grant_consent(site="demo.example", user="dana", confirm=True)
    preview = server.import_obsidian(path=str(vault), site="demo.example", user="dana")
    assert preview["dry_run"] is True and preview["events_added"] == 0
    assert svc.recall("demo.example", "dana") == []
    done = server.import_obsidian(path=str(vault), site="demo.example", user="dana",
                                  dry_run=False)
    assert done["events_added"] == 1


def test_tool_signatures_still_visible_to_mcp():
    import inspect
    params = inspect.signature(server.recall_card).parameters
    assert "site" in params and "user" in params and "context" in params
    assert inspect.signature(server.grant_consent).parameters["confirm"].default is False
