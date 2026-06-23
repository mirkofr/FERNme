"""Curation wired into observe(): OFF by default, and when ON it supersedes
(tombstones) or raises a question, with inferred never silently overriding
explicit."""
import dataclasses

from fernme.service import FernService
from fernme.store.sqlite_store import SQLiteStore
from fernme.config import DEFAULT


def _svc(curation=True):
    cfg = dataclasses.replace(DEFAULT, curation=curation)
    s = FernService(store=SQLiteStore(":memory:"), cfg=cfg)
    s.store.set_consent("demo.com", "elena", True)
    return s


def test_off_by_default_changes_nothing():
    s = _svc(curation=False)
    out = s.observe("demo.com", "elena", "chat", {"tags": ["diet:vegetarian"]})
    assert "questions" not in out and "superseded" not in out


def test_explicit_supersedes_same_slot():
    s = _svc()
    s.observe("demo.com", "elena", "chat", {"tags": ["diet:vegetarian"]}, ts=1.0)
    out = s.observe("demo.com", "elena", "chat", {"tags": ["diet:pescatarian"]}, ts=2.0)
    assert any(x["old"] == "diet:vegetarian" for x in out["superseded"])
    ug = s.store.load_user("demo.com", "elena")
    assert ug.edges["diet:vegetarian"].source == "superseded"   # tombstoned, not gone


def test_polarity_supersede():
    s = _svc()
    s.observe("demo.com", "elena", "chat", {"tags": ["likes:coffee"]}, ts=1.0)
    out = s.observe("demo.com", "elena", "chat", {"tags": ["!likes:coffee"]}, ts=2.0)
    assert any(x["old"] == "likes:coffee" for x in out["superseded"])


def test_inferred_never_silently_overrides_explicit():
    s = _svc()
    s.observe("demo.com", "elena", "chat", {"tags": ["diet:vegetarian"]}, ts=1.0)  # explicit
    out = s.observe("demo.com", "elena", "chat",
                    {"tags": ["likes:steak"], "source": "guessed"}, ts=2.0)  # inferred
    qs = out["questions"]
    assert qs and qs[0]["old"] == "diet:vegetarian" and "steak" in qs[0]["question"]
    # the explicit fact was NOT silently overwritten
    ug = s.store.load_user("demo.com", "elena")
    assert ug.edges["diet:vegetarian"].source != "superseded"


def test_no_conflict_no_noise():
    s = _svc()
    s.observe("demo.com", "elena", "chat", {"tags": ["likes:coffee"]}, ts=1.0)
    out = s.observe("demo.com", "elena", "chat", {"tags": ["topic:python"]}, ts=2.0)
    assert out["questions"] == [] and out["superseded"] == []
