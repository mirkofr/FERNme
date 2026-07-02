"""Ingestion bridge: namespaced controlled vocabulary. Run: pytest -q tests/test_vocabulary.py"""
import sys, os, tempfile, json
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
    assert v.canonical("!BIO") == "!pref:organic"


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


def test_resolve_returns_alias_for_provenance():
    v = Vocabulary.from_spec({"person:mrs-reyes": ["reyes-dana"]})
    assert v.resolve("reyes-dana") == ("person:mrs-reyes", "reyes-dana")
    assert v.resolve("person:mrs-reyes") == ("person:mrs-reyes", None)


def test_human_aliases_match_sanitized_tag_tokens():
    v = Vocabulary.from_spec({
        "company:memoryforge-labs": ["MemoryForge Labs"],
        "role:senior-product-manager": ["senior pm"],
    })
    assert v.canonical("memoryforgelabs") == "company:memoryforge-labs"
    assert v.canonical("seniorpm") == "role:senior-product-manager"


def test_alias_provenance_recorded_without_extra_active_edges():
    v = Vocabulary.from_spec({
        "person:mrs-reyes": ["mrs-reyes", "linked_label:mrs-reyes"],
    })
    svc = _svc(vocabulary=v); svc.consent("s", "u", True)
    svc.observe("s", "u", "note", {
        "tags": ["mrs-reyes", "linked_label:mrs-reyes"],
        "text": "source sentence",
        "source": "stated",
    })

    events = svc.recall("s", "u", limit=1)
    assert [attr for attr, _mag in events[0]["attrs"]] == ["person:mrs-reyes"]
    assert events[0]["payload"]["aliases"] == {
        "mrs-reyes": "person:mrs-reyes",
        "linked_label:mrs-reyes": "person:mrs-reyes",
    }
    assert events[0]["payload"]["text"] == "source sentence"
    assert events[0]["payload"]["source"] == "stated"
    edges = svc.store.load_user("s", "u").edges
    assert set(edges) == {"person:mrs-reyes"}


def test_same_surname_does_not_merge_without_explicit_alias():
    v = Vocabulary.from_spec({
        "person:mrs-reyes": ["reyes-dana"],
        "person:mr-reyes": ["reyes-remy"],
    })
    assert v.canonical("reyes-dana") == "person:mrs-reyes"
    assert v.canonical("reyes-remy") == "person:mr-reyes"
    assert v.canonical("reyes") == "pref:reyes"


def test_vocabulary_json_is_editable_glass_box():
    fd, path = tempfile.mkstemp(suffix=".json"); os.close(fd)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"person:mrs-reyes": ["reyes-dana"]}, f)
        v = Vocabulary.from_json(path)
        assert v.canonical("reyes-dana") == "person:mrs-reyes"

        out = path + ".out"
        v.write_json(out)
        with open(out, encoding="utf-8") as f:
            exported = json.load(f)
        assert exported == {"person:mrs-reyes": ["reyes-dana"]}
    finally:
        for p in (path, path + ".out"):
            try:
                os.remove(p)
            except OSError:
                pass
