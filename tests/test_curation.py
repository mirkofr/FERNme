"""The editing policy: conflict detection (all 3 kinds), authority resolution
(inferred never silently overrides explicit), and the clarifying question."""
from dataclasses import dataclass

from fernme import curation as cur


@dataclass
class FakeEdge:
    source: str = "known"
    last_reinforced: float = 0.0


def _ex(**kw):
    return {a: FakeEdge(**v) for a, v in kw.items()}


# ---- 1. conflict detection beyond polarity --------------------------------
def test_polarity_conflict():
    assert cur.detect("likes:steak", ["!likes:steak"]) == [("!likes:steak", "polarity")]


def test_same_slot_value_change():
    # single-value slot: vegetarian -> pescatarian is a conflict
    assert cur.detect("diet:pescatarian", ["diet:vegetarian"]) == [("diet:vegetarian", "same-slot")]


def test_multi_value_slot_is_not_a_conflict():
    # likes: is multi-value; two likes coexist, no conflict
    assert cur.detect("likes:tea", ["likes:coffee"]) == []


def test_cross_slot_semantic_conflict():
    assert cur.detect("likes:steak", ["diet:vegetarian"]) == [("diet:vegetarian", "semantic")]


def test_exclusive_group_conflict():
    assert cur.detect("pref:light-mode", ["pref:dark-mode"]) == [("pref:dark-mode", "semantic")]


# ---- 2. authority axis -----------------------------------------------------
def test_inferred_never_silently_overrides_explicit():
    # old is an explicit (known) statement; new is inferred (guessed) -> ASK
    existing = _ex(**{"diet:vegetarian": {"source": "known"}})
    res = cur.review("likes:steak", "guessed", 5.0, existing, importance=0.9)
    assert len(res) == 1 and res[0].action == "ask"
    assert "vegetarian" in res[0].question and "steak" in res[0].question


def test_explicit_supersedes_inferred():
    existing = _ex(**{"diet:vegetarian": {"source": "guessed"}})
    res = cur.review("diet:pescatarian", "known", 5.0, existing, importance=0.9)
    assert res[0].action == "supersede"


def test_equal_authority_newer_wins():
    existing = _ex(**{"diet:vegetarian": {"source": "known", "last_reinforced": 1.0}})
    res = cur.review("diet:pescatarian", "known", 9.0, existing)
    assert res[0].action == "supersede"


def test_low_importance_tension_is_held_not_asked():
    existing = _ex(**{"diet:vegetarian": {"source": "known"}})
    res = cur.review("likes:steak", "guessed", 5.0, existing, importance=0.1)
    assert res[0].action == "hold" and res[0].question == ""


def test_no_conflict_returns_empty():
    existing = _ex(**{"likes:coffee": {"source": "known"}})
    assert cur.review("topic:python", "known", 1.0, existing) == []
