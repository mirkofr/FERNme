"""Bounded reinforcement history keeps base-level activation within a small error."""
import random
from dataclasses import replace

import pytest

from fernme.config import DEFAULT
from fernme.core.graph import AssocGraph, Event, UserGraph
from fernme.retrieve.activation import base_level
from fernme.write.hebbian import observe


def _feed(cfg, times):
    ug, ag = UserGraph("s", "u"), AssocGraph("s")
    for t in times:
        observe(ug, ag, Event("s", "u", t, "chat", {}), [("pref:x", 1.0)], cfg)
    return ug


def _times(pattern, n=600, seed=1):
    rng, t, out = random.Random(seed), 0.0, []
    for _ in range(n):
        if pattern == "even":
            t += 1.0
        else:
            t += rng.random() * 0.2 if rng.random() < 0.8 else rng.random() * 30
        out.append(t)
    return out


def test_history_is_capped_keeping_first_and_most_recent():
    times = _times("even", 200)
    ug = _feed(DEFAULT, times)
    kept = ug.history["pref:x"]
    assert len(kept) == DEFAULT.history_cap
    assert kept[0] == times[0]
    assert kept[-(DEFAULT.history_cap - 1):] == times[-(DEFAULT.history_cap - 1):]
    assert ug.edges["pref:x"].hits == 200


def test_cap_zero_keeps_everything():
    ug = _feed(replace(DEFAULT, history_cap=0), _times("even", 200))
    assert len(ug.history["pref:x"]) == 200


@pytest.mark.parametrize("pattern", ["even", "bursty"])
def test_capped_base_level_tracks_exact_value(pattern):
    times = _times(pattern)
    exact_cfg = replace(DEFAULT, history_cap=0)
    exact, capped = _feed(exact_cfg, times), _feed(DEFAULT, times)
    for now in (times[-1] + 1, times[-1] + 50, times[-1] + 500):
        diff = abs(base_level(exact, "pref:x", now, exact_cfg)
                   - base_level(capped, "pref:x", now, DEFAULT))
        assert diff < 0.02


def test_short_histories_are_unchanged():
    times = _times("even", 20)
    exact_cfg = replace(DEFAULT, history_cap=0)
    a, b = _feed(exact_cfg, times), _feed(DEFAULT, times)
    assert a.history == b.history
    assert base_level(a, "pref:x", 30.0, exact_cfg) == base_level(b, "pref:x", 30.0, DEFAULT)
