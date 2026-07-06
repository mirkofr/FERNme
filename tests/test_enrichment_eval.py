import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from fernme.eval.enrichment import run, summarize


def test_synthetic_enrichment_eval_reports_mock_delta():
    rows = run(range(2))
    summary = summarize(rows)

    assert summary["off_recall"]["mean"] == 0.0
    assert summary["on_recall"]["mean"] == 1.0
    assert summary["on_precision"]["mean"] == 1.0
    assert summary["on_dropped"]["mean"] == 1.0
