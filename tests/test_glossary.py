"""Native per-memory meaning: namespace templates (0 tokens), supplied glosses,
context from the event sentence, and the service.glossary() assembly.
Uses the Elena demo persona (demo/elena), never real user data."""
from fernme import glossary as g
from fernme.service import FernService
from fernme.store.sqlite_store import SQLiteStore


def test_namespace_template_is_deterministic():
    assert g.gloss_for("pref:markdown") == "a stated preference"
    assert g.gloss_for("rel:keiko") == "a person in their network"
    assert g.gloss_for("topic:hci") == "a topic of interest"
    assert g.gloss_for("!pref:vague-ai-answers").startswith("a dislike")


def test_custom_gloss_wins_over_template():
    assert g.gloss_for("pref:flat-white", "her go-to coffee order") == \
        "her go-to coffee order"


def test_assemble_latest_gloss_and_context_win():
    events = [
        {"ts": 1.0, "payload": {"tags": ["pref:flat-white"], "text": "first mention",
                                "glosses": {"pref:flat-white": "coffee"}}},
        {"ts": 2.0, "payload": {"tags": ["pref:flat-white"], "text": "one sugar, please",
                                "glosses": {"pref:flat-white": "flat white, one sugar"}}},
    ]
    gl = g.assemble(events)
    assert gl["pref:flat-white"]["gloss"] == "flat white, one sugar"
    assert gl["pref:flat-white"]["context"] == "one sugar, please"


def test_assemble_falls_back_to_template_when_no_gloss():
    gl = g.assemble([{"ts": 1.0, "payload": {"tags": ["pref:markdown"], "text": "takes notes in markdown"}}])
    assert gl["pref:markdown"]["gloss"] == "a stated preference"
    assert gl["pref:markdown"]["context"] == "takes notes in markdown"


def test_service_glossary_end_to_end():
    svc = FernService(store=SQLiteStore(":memory:"))
    svc.store.set_consent("demo.com", "elena", True)
    svc.observe("demo.com", "elena", "chat", {"tags": ["pref:flat-white"],
                "text": "elena always orders a flat white with one sugar",
                "glosses": {"pref:flat-white": "flat white, one sugar"}})
    svc.observe("demo.com", "elena", "chat", {"tags": ["pref:markdown"]})  # no gloss -> template
    gl = svc.glossary("demo.com", "elena")
    assert gl["pref:flat-white"]["gloss"] == "flat white, one sugar"
    assert "one sugar" in gl["pref:flat-white"]["context"]
    assert gl["pref:markdown"]["gloss"] == "a stated preference"  # deterministic, 0 tokens
