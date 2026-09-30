"""Mem0 head-to-head harness: fairness helpers and key-less plumbing (no API calls)."""
from fernme.eval import harness as H
from fernme.eval import mem0_h2h as X


def test_event_sentence_carries_every_tag_as_plain_english():
    ev = H.HarnessEvent(3.0, "purchase", ("pref:jasmine-tea", "!pref:espresso"), "Visit.")
    s = X.event_sentence(ev)
    assert s.startswith("Day 3: during a purchase")
    assert "jasmine tea" in s
    assert "does not like prefers espresso" in s
    assert s.endswith("Visit.")


def test_mapper_ranks_by_memory_order_and_dedupes():
    universe = ["pref:jasmine-tea", "style:minimal", "size:medium"]
    got = X.memories_to_attrs(
        ["Prefers jasmine tea and minimal style", "Jasmine tea again; size medium"], universe, 5)
    assert got == ["pref:jasmine-tea", "style:minimal", "size:medium"]


def test_mapper_negation_is_clause_scoped():
    universe = ["pref:dark-roast", "pref:mint-tea"]
    got = X.memories_to_attrs(
        ["User no longer drinks dark roast and now prefers mint tea."], universe, 5)
    assert got == ["pref:mint-tea"]


def test_mapper_does_not_treat_value_words_as_negation():
    assert X.memories_to_attrs(["Currently no snacks"], ["fast:no-snacks"], 5) == ["fast:no-snacks"]


def test_check_is_offline_and_reports_missing_key():
    rep = X.check(1, env={})
    assert rep["openai_api_key_set"] is False
    assert rep["ready"] is False
    assert rep["mem0_add_calls"] > 0
    assert rep["scenario_runs"] == len(X.REGIMES)


def test_stub_run_scores_every_method_on_every_regime():
    rep = X.run(X.StubBackend(), seeds=1, k=5)
    assert rep["mode"] == "synthetic-mem0-head-to-head"
    assert set(rep["summary"]) == set(X.REGIMES)
    for regime in X.REGIMES:
        assert set(rep["summary"][regime]) == set(X.BASELINES) | {"mem0"}
        fern = rep["summary"][regime]["fern_pure"]
        assert fern["llm_calls"]["mean"] == 0.0
        for method in rep["summary"][regime].values():
            assert 0.0 <= method["recall_at_k"]["mean"] <= 1.0
    assert any("Synthetic" in c for c in rep["caveats"])


def test_cli_check_exit_code_without_key(monkeypatch, capsys):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert X.main(["--check", "--seeds", "1"]) == 1
    assert "Not ready" in capsys.readouterr().out
