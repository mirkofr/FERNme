"""Capture layer: adapters propose tags, pipeline writes them via the 0-LLM path,
config round-trips, and token costs are reported honestly."""
from fernme.service import FernService
from fernme.store.sqlite_store import SQLiteStore
from fernme.capture import (build_adapters, default_config, load_config,
                            write_config, CapturePipeline)
from fernme.capture.signal_hooks import SignalAdapter
from fernme.capture.agent_byproduct import AgentByproductAdapter
from fernme.capture.local_tagger import LocalTaggerAdapter


def test_signal_is_zero_token_and_deterministic():
    a = SignalAdapter()
    assert a.cost_tokens == 0
    assert a.extract({"kind": "command", "cmd": "git commit -m x"}) == ["habit:cli", "tool:git"]
    assert "topic:python" in a.extract({"kind": "file", "path": "/p/proj/x.py"})
    git = a.extract({"kind": "git", "repo": "FERNme", "msg": "feat: y"})
    assert "project:fernme" in git and "activity:feature" in git
    assert a.extract({"kind": "chat", "text": "hello"}) == []  # ignores chat


def test_agent_parses_byproduct_line_and_costs_tokens():
    a = AgentByproductAdapter()
    assert a.cost_tokens > 0
    tags = a.extract({"kind": "chat", "text": "sure. FERN_TAGS: pref:concise topic:python"})
    assert "pref:concise" in tags and "topic:python" in tags
    assert a.extract({"kind": "chat", "text": "<!--FERN goal:launch-->"}) == ["goal:launch"]


def test_local_rules_mode_is_zero_token():
    a = LocalTaggerAdapter(mode="rules")
    assert a.cost_tokens == 0
    tags = a.extract({"kind": "chat", "text": "please keep it concise and use dark mode"})
    assert "pref:concise" in tags and "pref:dark-mode" in tags


def test_pipeline_writes_through_engine_and_reports_cost():
    svc = FernService(store=SQLiteStore(":memory:"))
    svc.store.set_consent("demo.com", "elena", True)
    pipe = CapturePipeline(svc, "demo.com", "elena",
                           build_adapters(default_config(active=["agent", "signal"])))
    r = pipe.ingest({"kind": "chat", "text": "FERN_TAGS: pref:concise"})
    assert "pref:concise" in r["stored_attrs"]
    assert r["billed_tokens"] == 30 and r["adapters_fired"] == ["agent"]
    r2 = pipe.ingest({"kind": "command", "cmd": "python x.py"})
    assert r2["billed_tokens"] == 0  # signal is free


def test_config_round_trip(tmp_path):
    p = str(tmp_path / "fern.toml")
    write_config(default_config(active=["signal", "local"]), p)
    cfg = load_config(p)
    assert cfg["active"] == ["signal", "local"]
    assert cfg["local"]["mode"] == "rules"
