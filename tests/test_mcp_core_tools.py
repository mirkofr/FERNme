"""record_outcome / why / export_memory / near-duplicate hints over MCP (fictional data)."""
import json
import os

import pytest

pytest.importorskip("mcp")

from fernme.api import mcp_server as server
from fernme.service import FernService

SITE, USER = "demo.example", "dana"


@pytest.fixture()
def svc(tmp_path, monkeypatch):
    for var in ("FERNME_SITE", "FERNME_USER", "FERNME_ALLOW_OTHER_PROFILES"):
        monkeypatch.delenv(var, raising=False)
    service = FernService(db_path=str(tmp_path / "core.db"))
    monkeypatch.setattr(server, "svc", service)
    server.grant_consent(site=SITE, user=USER, confirm=True)
    return service


def test_record_outcome_strengthens_and_weakens(svc):
    server.remember(site=SITE, user=USER, tags=["pref:window-seat", "pref:aisle-seat"])
    before = svc.store.load_user(SITE, USER).edges
    w_window, w_aisle = before["pref:window-seat"].weight, before["pref:aisle-seat"].weight
    server.record_outcome(True, ["pref:window-seat"], site=SITE, user=USER, now=1.0)
    server.record_outcome(False, ["pref:aisle-seat"], site=SITE, user=USER, now=2.0)
    after = svc.store.load_user(SITE, USER).edges
    assert after["pref:window-seat"].weight > w_window
    assert after["pref:aisle-seat"].weight < w_aisle


def test_why_explains_evidence(svc):
    for t in (1.0, 2.0, 3.0):
        server.remember(site=SITE, user=USER, tags=["pref:tea"], ts=t)
    server.record_outcome(True, ["pref:tea"], site=SITE, user=USER, now=4.0)
    out = server.why("pref:tea", site=SITE, user=USER)
    assert out["observations"] == 3 and out["good_outcomes"] == 1
    assert out["first_seen"] == 1.0 and out["last_seen"] == 4.0


def test_export_memory_writes_file_and_returns_only_counts(svc):
    server.remember(site=SITE, user=USER, tags=["pref:tea"], text="Dana likes tea.")
    out = server.export_memory(site=SITE, user=USER)
    assert set(out) == {"path", "memories", "events"}
    assert out["memories"] == 1 and "Dana likes tea" not in json.dumps(out)
    with open(out["path"], encoding="utf-8") as fh:
        data = json.load(fh)
    assert "pref:tea" in data["edges"]
    if os.name == "posix":
        assert oct(os.stat(out["path"]).st_mode & 0o777) == "0o600"


def test_remember_flags_near_duplicate_spellings(svc):
    server.remember(site=SITE, user=USER, tags=["pref:oat-milk", "pref:tea"])
    out = server.remember(site=SITE, user=USER, tags=["pref:oat_milk", "likes:tea", "pref:jazz"])
    assert out["near_duplicates"] == {"pref:oat_milk": ["pref:oat-milk"],
                                      "likes:tea": ["pref:tea"]}
    clean = server.remember(site=SITE, user=USER, tags=["pref:tea"])
    assert "near_duplicates" not in clean


def test_profile_lock_applies_to_new_tools(svc, monkeypatch):
    monkeypatch.setenv("FERNME_SITE", SITE)
    monkeypatch.setenv("FERNME_USER", USER)
    with pytest.raises(server.ProfileLockedError):
        server.export_memory(site=SITE, user="someone-else")
    with pytest.raises(server.ProfileLockedError):
        server.record_outcome(True, [], site="other.example", user=USER)
