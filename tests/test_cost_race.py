"""Synthetic cost race: deterministic stream, flat FERNme card, growing history."""
import importlib.util

import pytest

from fernme.eval import cost_race as R


def test_stream_is_deterministic_and_drifts_at_midpoint():
    a, b = R.synthetic_stream(40, seed=3), R.synthetic_stream(40, seed=3)
    assert a == b
    early = {t for m in a[:20] for t in m["tags"]}
    late = {t for m in a[20:] for t in m["tags"]}
    assert "topic:python" in early and "topic:python" not in late
    assert "topic:rust" in late and "topic:rust" not in early


def test_fern_card_stays_bounded_while_history_grows():
    rep = R.run(turns=200)
    fern, hist = rep["fern"]["read_tokens"], rep["history"]["read_tokens"]
    assert len(fern) == len(hist) == 200
    assert rep["fern"]["llm_calls_cum"][-1] == 0
    assert max(fern[100:]) <= 2 * max(fern[:100])
    assert all(b >= a for a, b in zip(hist, hist[1:]))
    assert hist[-1] > 50 * fern[-1]
    assert rep["mode"] == "synthetic-cost-race"


@pytest.mark.skipif(importlib.util.find_spec("mem0") is not None,
                    reason="exercises the not-installed path")
def test_mem0_series_skips_cleanly_when_not_installed():
    rep = R.run(turns=5, with_mem0=True)
    assert rep["mem0"] is None
    assert any("skipped" in n for n in rep["notes"])
