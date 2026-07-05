import json
from dataclasses import replace

from fernme.config import DEFAULT
from fernme.eval import harness


def test_harness_reports_required_regimes_methods_and_metrics():
    report = harness.run(seeds=2, k=5)

    assert report["mode"] == "synthetic-eval-harness"
    assert report["regimes"] == ["static", "drift", "contextual"]
    assert report["methods"] == [
        "fern_pure", "fern_entities", "recency", "frequency", "bm25"]
    for regime in report["regimes"]:
        assert set(report["summary"][regime]) == set(report["methods"])
        for method in report["methods"]:
            assert set(report["summary"][regime][method]) == set(report["metrics"])
            assert report["summary"][regime][method]["llm_calls"]["mean"] == 0.0


def test_harness_is_deterministic_for_same_seed_window():
    first = harness.run(seeds=2, k=5, seed_offset=3)
    second = harness.run(seeds=2, k=5, seed_offset=3)

    assert first == second


def test_harness_writes_json_report(tmp_path):
    out = tmp_path / "harness.json"
    report = harness.main(["--seeds", "1", "--json", str(out)])

    loaded = json.loads(out.read_text(encoding="utf-8"))
    assert loaded == report
    assert loaded["summary"]["drift"]["fern_pure"]["stale_recall_rate"]["mean"] >= 0.0


def test_bm25_cabinet_baseline_uses_event_text_for_contextual_probe():
    report = harness.run(seeds=1, k=5)

    bm25 = report["summary"]["contextual"]["bm25"]
    assert bm25["recall_at_k"]["mean"] > 0.0
    assert bm25["token_estimate"]["mean"] > report["summary"]["contextual"]["frequency"]["token_estimate"]["mean"]


def test_harness_accepts_config_driven_control_changes():
    wide = harness.run(seeds=1, cfg=replace(DEFAULT, top_n=8), k=5)
    narrow = harness.run(seeds=1, cfg=replace(DEFAULT, top_n=2), k=5)

    assert (
        narrow["summary"]["static"]["fern_pure"]["token_estimate"]["mean"]
        <= wide["summary"]["static"]["fern_pure"]["token_estimate"]["mean"]
    )
