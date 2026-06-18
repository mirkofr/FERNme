"""Ingestion bridge: namespaced controlled vocabulary. Run: pytest -q tests/test_vocabulary.py"""
import sys, os, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from fernme.service import FernService
from fernme.vocabulary import Vocabulary
from fernme.tagging import LLMTagger

SPEC = {
    "pref:written_communication": ["written_steps", "prefers_written", "email_pref"],
    "pref:organic": ["organic", "bio", "all_natural"],
    "topic:billing": ["invoice", "payment_issue"],
}


def _svc(**kw):
    fd, p = tempfile.mkstemp(suffix=".db"); os.close(fd); os.remove(p)
    return FernService(p, **kw)


def test_aliases_collapse_to_one_canonical():
    v = Vocabulary.from_spec(SPEC)
    assert v.canonical("written_steps") == "pref:written_communication"
    assert v.canonical("prefers_written") == "pref:written_communication"
    assert v.canonical("BIO") == "pref:organic"


def test_cross_observation_consistency_no_drift():
    # THE foundation: same concept via 3 different aliases over time -> ONE edge.
    v = Vocabulary.from_spec(SPEC)
    svc = _svc(vocabulary=v); svc.consent("s", "u", True)
    svc.observe("s", "u", "n", {"tags": ["written_steps"]})
    svc.observe("s", "u", "n", {"tags": ["prefers_written"]})
    svc.observe("s", "u", "n", {"tags": ["email_pref"]})
    edges = svc.store.load_user("s", "u").edges
    assert "pref:written_communication" in edges
    assert edges["pref:written_communication"].hits == 3        # all merged
    assert "written_steps" not in edges and "email_pref" not in edges


def test_without_vocab_drifts_into_separate_edges():
    svc = _svc(); svc.consent("s", "u", True)                   # no vocabulary
    for t in ["written_steps", "prefers_written", "email_pref"]:
        svc.observe("s", "u", "n", {"tags": [t]})
    assert svc.store.load_user("s", "u").n_edges() == 3         # drift -> 3 weak edges


def test_strict_drops_unknown_lenient_namespaces():
    strict = Vocabulary.from_spec(SPEC, strict=True)
    assert strict.canonical("totally_unknown") is None
    lenient = Vocabulary.from_spec(SPEC)
    assert lenient.canonical("totally_unknown") == "pref:totally_unknown"


def test_catalog_path_normalized():
    v = Vocabulary.from_spec(SPEC)
    svc = _svc(vocabulary=v, catalog={"item1": ["organic", "bio"]})
    svc.consent("s", "u", True)
    svc.observe("s", "u", "purchase", {"item_id": "item1"})
    edges = svc.store.load_user("s", "u").edges
    assert "pref:organic" in edges and "organic" not in edges   # catalog tag canonicalized


def test_llm_tagger_output_normalized():
    v = Vocabulary.from_spec(SPEC)
    tagger = LLMTagger(lambda p: "prefers_written, invoice")    # messy/alias output
    svc = _svc(memory_mode="gated", tagger=tagger, vocabulary=v)
    svc.consent("s", "u", True)
    svc.observe("s", "u", "chat", {"text": "some novel message"})
    wire = svc.card("s", "u")["wire"]
    assert "pref:written_communication" in wire and "topic:billing" in wire
