"""v3: communication-style/mood (#9), domain-agnostic outcomes (#2),
provenance (#8). Examples are deliberately NON-commerce. Run: pytest -q"""
import sys, os, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from fernme.service import FernService


def _svc():
    fd, p = tempfile.mkstemp(suffix=".db"); os.close(fd); os.remove(p)
    return FernService(p)


# ---- #9 style + mood ----
def test_style_detects_frustration_support_bot():
    svc = _svc(); svc.consent("support", "u", True)
    svc.observe("support", "u", "chat", {"text": "ugh this is STILL broken again, so frustrated!!"})
    card = svc.style_card("support", "u")
    assert card["mood"] < 0
    assert any("frustrated" in t or "high_energy" in t for t in card["style"])
    assert "empathy" in card["guidance"]


def test_style_formal_vs_casual():
    svc = _svc()
    svc.consent("clinic", "formal", True); svc.consent("clinic", "casual", True)
    svc.observe("clinic", "formal", "chat", {"text": "Could you kindly help me reschedule? Thank you."})
    svc.observe("clinic", "casual", "chat", {"text": "hey yeah can u move my appt lol"})
    assert "style:formal" in svc.style_card("clinic", "formal")["style"]
    assert "style:casual" in svc.style_card("clinic", "casual")["style"]


def test_mood_trend_declines(  ):
    svc = _svc(); svc.consent("tutor", "u", True)
    svc.observe("tutor", "u", "chat", {"text": "this is great, I love learning this, awesome!"})
    svc.observe("tutor", "u", "chat", {"text": "ugh I'm so confused and frustrated, this is wrong again"})
    card = svc.style_card("tutor", "u")
    assert card["mood_trend"] < 0                      # mood slid downward
    assert "sliding" in card["guidance"]


# ---- #2 domain-agnostic outcomes ----
def test_outcome_reinforces_on_success():
    svc = _svc(); svc.consent("clinic", "u", True)
    for _ in range(2):
        svc.observe("clinic", "u", "visit", {"tags": ["needs_wheelchair_access"]})
    before = svc.store.load_user("clinic", "u").edges["needs_wheelchair_access"].weight
    svc.record_outcome("clinic", "u", success=True, attrs=["needs_wheelchair_access"])
    after = svc.store.load_user("clinic", "u").edges["needs_wheelchair_access"].weight
    assert after > before                              # goal achieved -> reinforce


def test_outcome_penalizes_on_failure():
    svc = _svc(); svc.consent("helpdesk", "u", True)
    for _ in range(4):
        svc.observe("helpdesk", "u", "ticket", {"tags": ["prefers_phone_callback"]})
    before = svc.store.load_user("helpdesk", "u").edges["prefers_phone_callback"].weight
    svc.record_outcome("helpdesk", "u", success=False, attrs=["prefers_phone_callback"])
    after = svc.store.load_user("helpdesk", "u").edges["prefers_phone_callback"].weight
    assert after < before                              # backfired -> weaken


# ---- #8 explainability ----
def test_why_returns_evidence():
    svc = _svc(); svc.consent("booking", "u", True)
    for _ in range(3):
        svc.observe("booking", "u", "reservation", {"tags": ["window_seat"]})
    svc.record_outcome("booking", "u", True, attrs=["window_seat"])
    svc.record_outcome("booking", "u", False, attrs=["window_seat"])
    w = svc.why("booking", "u", "window_seat")
    assert w["observations"] == 3 and w["good_outcomes"] == 1 and w["bad_outcomes"] == 1
    assert w["first_seen"] is not None
