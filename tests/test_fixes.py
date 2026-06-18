"""Fixes from external review: catalog mapping (#2), differential prune (#3),
non_english false positive (#5). Run: pytest -q tests/test_fixes.py"""
import sys, os, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from fernme.service import FernService
from fernme.style import analyze


def _svc(**kw):
    fd, p = tempfile.mkstemp(suffix=".db"); os.close(fd); os.remove(p)
    return FernService(p, **kw)


def test_catalog_maps_item_id_without_tags():
    svc = _svc(catalog={"item1": ["organic", "dairy"]})
    svc.consent("s", "u", True)
    svc.observe("s", "u", "purchase", {"item_id": "item1"})   # no tags, only item_id
    wire = svc.card("s", "u")["wire"]
    assert "organic" in wire and "dairy" in wire             # catalog lookup worked


def test_prune_keeps_deviations_drops_redundant():
    svc = _svc()
    for i in range(5):                                        # build a prior: mean(morning) high
        svc.consent("s", f"u{i}", True)
        for _ in range(5):
            svc.observe("s", f"u{i}", "v", {"tags": ["morning"]})
    svc.prior_refresh("s")
    svc.consent("s", "u", True)
    for _ in range(5):
        svc.observe("s", "u", "v", {"tags": ["morning"]})     # ~= prior mean -> redundant
    for _ in range(5):
        svc.observe("s", "u", "v", {"tags": ["night_owl"]})   # prior doesn't know it -> deviation
    res = svc.prune_to_prior("s", "u")
    edges = set(svc.store.load_user("s", "u").edges)
    assert "morning" not in edges                             # redundant pruned
    assert "night_owl" in edges                               # deviation kept
    assert svc.store.load_prior("s").mean("morning") > 1      # value recoverable from prior
    assert res["pruned"] >= 1


def test_non_english_no_false_positive():
    smart = analyze('She said “this is nice” — but stayed guarded.')["style_tags"]
    assert "style:non_english" not in smart                  # curly quotes/dash are fine
    korean = analyze("안녕하세요 반갑습니다")["style_tags"]
    assert "style:non_english" in korean                     # real non-Latin still flagged
