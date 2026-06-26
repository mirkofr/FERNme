"""memory_mode switch (pure / gated / offline) with a MOCK LLM. Run: pytest -q"""
import sys, os, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from fernme.service import FernService
from fernme.tagging import LLMTagger


def _svc(**kw):
    fd, p = tempfile.mkstemp(suffix=".db"); os.close(fd); os.remove(p)
    return FernService(p, **kw)


def test_pure_extracts_no_content_and_no_llm():
    # pure mode: no LLM call, and no CONTENT attributes from prose (it can't read
    # meaning without a tagger). It DOES still learn deterministic style — that's
    # key-less and runs in every mode.
    svc = _svc(memory_mode="pure")            # no tagger, no key
    svc.consent("s", "u", True)
    svc.observe("s", "u", "chat", {"text": "I only buy organic and avoid dairy"})
    wire = svc.card("s", "u")["wire"]
    assert svc.llm_calls == 0
    assert "organic" not in wire and "dairy" not in wire   # content not understood
    assert "style:" not in wire
    assert svc.style_card("s", "u")["style"]                # but guidance still works


def test_gated_fires_only_on_novelty():
    calls = {"n": 0}
    def fake_llm(prompt):
        calls["n"] += 1
        return "organic, dairy_free"
    tagger = LLMTagger(fake_llm)
    svc = _svc(memory_mode="gated", tagger=tagger)
    svc.consent("s", "u", True)
    # structured event WITH tags -> deterministic succeeds -> LLM NOT called
    svc.observe("s", "u", "purchase", {"tags": ["milk"], "text": "bought milk"})
    assert calls["n"] == 0 and svc.llm_calls == 0
    # free text with NO tags -> novelty -> one LLM call, attributes learned
    svc.observe("s", "u", "chat", {"text": "I'm vegan and love organic"})
    assert calls["n"] == 1 and svc.llm_calls == 1
    wire = svc.card("s", "u")["wire"]
    assert "organic" in wire and "dairy_free" in wire


def test_gated_constrains_to_vocabulary():
    tagger = LLMTagger(lambda p: "organic, made_up_token", vocabulary=["organic", "vegan"])
    svc = _svc(memory_mode="gated", tagger=tagger)
    svc.consent("s", "u", True)
    svc.observe("s", "u", "chat", {"text": "..."})
    wire = svc.card("s", "u")["wire"]
    assert "organic" in wire and "made_up_token" not in wire   # off-vocab dropped


def test_offline_consolidation_adds_nuance():
    enricher = LLMTagger(lambda p: "hosts_dinner_parties")     # nuance a counter can't get
    svc = _svc(memory_mode="offline", enricher=enricher)
    svc.consent("s", "u", True)
    for _ in range(3):
        svc.observe("s", "u", "chat", {"text": "bought wine and cheese for guests again"})
    out = svc.consolidate("s", "u")
    assert "hosts_dinner_parties" in out["enriched"]
    assert "hosts_dinner_parties" in svc.card("s", "u")["wire"]


def test_offline_writes_stay_llm_free_on_hot_path():
    enricher = LLMTagger(lambda p: "x")
    svc = _svc(memory_mode="offline", enricher=enricher)
    svc.consent("s", "u", True)
    svc.observe("s", "u", "purchase", {"tags": ["organic"]})   # hot path: no LLM
    assert svc.llm_calls == 0
