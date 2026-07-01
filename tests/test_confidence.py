"""Multi-signal confidence + 3-tier gate + ask-budget. Run: pytest -q tests/test_confidence.py"""
import sys, os, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from fernme.service import FernService


def _svc(**kw):
    fd, p = tempfile.mkstemp(suffix=".db"); os.close(fd); os.remove(p)
    return FernService(p, **kw)


def test_strong_recent_evidence_acts():
    svc = _svc(); svc.consent("s", "u", True)
    for t in range(8):
        svc.observe("s", "u", "v", {"tags": ["organic"], "source": "stated"}, ts=t)
    res = svc.confidence("s", "u", "organic", now=8)      # lots of recent evidence
    assert 0.0 <= res["confidence"] <= 1.0
    assert res["gate"] == "act"


def test_stale_memory_downgrades():
    svc = _svc(); svc.consent("s", "u", True)
    for t in range(8):
        svc.observe("s", "u", "v", {"tags": ["organic"]}, ts=t)
    recent = svc.confidence("s", "u", "organic", now=8)["confidence"]
    stale = svc.confidence("s", "u", "organic", now=300)["confidence"]
    assert stale < recent                                  # not confirmed recently -> less sure
    assert svc.confidence("s", "u", "organic", now=300)["gate"] in ("observe", "ask")


def test_conflict_lowers_confidence():
    svc = _svc(); svc.consent("s", "u", True)
    for t in range(5):
        svc.observe("s", "u", "v", {"tags": ["dairy"]}, ts=t)
    base = svc.confidence("s", "u", "dairy", now=5)["confidence"]
    for t in range(5, 9):                                  # user now rejects dairy -> !dairy
        svc.observe("s", "u", "decline", {"tags": ["dairy"]}, ts=t)
    res = svc.confidence("s", "u", "dairy", now=9)
    assert res["conflict"] > 0 and res["confidence"] < base


def test_gate_tiers_and_ask_budget():
    svc = _svc(); svc.consent("s", "u", True)
    # an unknown attribute -> low confidence
    low_important = svc.confidence("s", "u", "unknown_pref", importance=0.9)
    assert low_important["gate"] == "ask"
    low_trivial = svc.confidence("s", "u", "unknown_pref", importance=0.1)
    assert low_trivial["gate"] == "ignore"
    # exhaust the ask budget -> 'ask' downgrades to 'observe' (no nagging)
    for _ in range(svc.cfg.ask_budget):
        svc.record_ask("s", "u")
    assert svc.confidence("s", "u", "unknown_pref", importance=0.9)["gate"] == "observe"
