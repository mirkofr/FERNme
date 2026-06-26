"""Salience: emotional/behavioral significance modulates forgetting."""
import sys, os, math
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from dataclasses import replace
from fernme.config import DEFAULT
from fernme.core.graph import UserGraph, AssocGraph, Event, Edge
from fernme.write.hebbian import observe, decay
from fernme.service import FernService
from fernme.store.sqlite_store import SQLiteStore
from fernme.retrieve.card import compile_card


def _seed(cfg, salient_intensity):
    ug = UserGraph("s", "u"); ag = AssocGraph("s")
    # one neutral and one strongly-salient single observation, same starting weight
    observe(ug, ag, Event("s","u",0.0,"v",{}), [("pref:neutral", 5.0)], cfg)
    observe(ug, ag, Event("s","u",0.0,"v",{}), [("pref:intense", 5.0)], cfg,
            salience={"pref:intense": salient_intensity})
    return ug, ag


def test_salience_slows_forgetting_when_enabled():
    cfg = replace(DEFAULT, salience_beta=0.9)
    ug, ag = _seed(cfg, 1.0)
    assert ug.edges["pref:intense"].salience >= 0.9
    for t in range(1, 120):                      # ~4 months of no reinforcement
        decay(ug, now=float(t), cfg=cfg)
    # the salient memory survives; the neutral one is forgotten (dropped below floor)
    assert "pref:intense" in ug.edges
    assert "pref:neutral" not in ug.edges


def test_default_off_is_backward_compatible():
    cfg = replace(DEFAULT, salience_beta=0.0)   # OFF
    ug, ag = _seed(cfg, 1.0)
    for t in range(1, 120):
        decay(ug, now=float(t), cfg=cfg)
    # with salience OFF, the intense edge gets no retention advantage -> both gone together
    assert ("pref:intense" in ug.edges) == ("pref:neutral" in ug.edges)


def test_text_emotion_adds_salience_to_mapped_facts():
    st = SQLiteStore(":memory:")
    svc = FernService(store=st)
    svc.consent("s", "neutral", True)
    svc.consent("s", "emotional", True)

    svc.observe("s", "neutral", "chat",
                {"tags": ["pref:coffee"], "text": "I like coffee."})
    svc.observe("s", "emotional", "chat",
                {"tags": ["pref:coffee"], "text": "I LOVE coffee!!"})

    neutral = svc.store.load_user("s", "neutral").edges["pref:coffee"].salience
    emotional = svc.store.load_user("s", "emotional").edges["pref:coffee"].salience
    assert emotional > neutral


def test_identity_namespace_gets_salience_floor():
    svc = FernService(store=SQLiteStore(":memory:"))
    svc.consent("s", "u", True)
    svc.observe("s", "u", "chat", {"tags": ["company:acme"], "text": "I work at Acme."})

    e = svc.store.load_user("s", "u").edges["company:acme"]
    assert e.salience >= DEFAULT.salience_identity


def test_identity_floor_survives_decay_vs_neutral_single_hit():
    cfg = DEFAULT
    svc = FernService(store=SQLiteStore(":memory:"), cfg=cfg)
    svc.consent("s", "u", True)
    svc.observe("s", "u", "chat", {"tags": ["company:acme", "topic:snacks"]})
    ug = svc.store.load_user("s", "u")

    for t in range(1, 15):
        decay(ug, now=float(t), cfg=cfg)

    assert "company:acme" in ug.edges
    assert "topic:snacks" not in ug.edges


def test_identity_sticky_survives_90_and_365_days():
    cfg = DEFAULT
    svc = FernService(store=SQLiteStore(":memory:"), cfg=cfg)
    svc.consent("s", "u", True)
    svc.observe("s", "u", "chat", {"tags": ["company:acme"]})
    ug = svc.store.load_user("s", "u")

    for t in range(1, 91):
        decay(ug, now=float(t), cfg=cfg)
    assert "company:acme" in ug.edges
    assert ug.edges["company:acme"].weight >= cfg.floor

    for t in range(91, 366):
        decay(ug, now=float(t), cfg=cfg)
    assert "company:acme" in ug.edges
    assert ug.edges["company:acme"].weight >= cfg.floor


def test_non_identity_facts_are_not_floor_exempt():
    cfg = DEFAULT
    svc = FernService(store=SQLiteStore(":memory:"), cfg=cfg)
    svc.consent("s", "neutral", True)
    svc.consent("s", "emotional", True)
    svc.observe("s", "neutral", "chat", {"tags": ["topic:snacks"]})
    svc.observe("s", "emotional", "chat",
                {"tags": ["likes:coffee"], "text": "I LOVE coffee!!"})

    neutral = svc.store.load_user("s", "neutral")
    emotional = svc.store.load_user("s", "emotional")
    for t in range(1, 366):
        decay(neutral, now=float(t), cfg=cfg)
        decay(emotional, now=float(t), cfg=cfg)

    assert "topic:snacks" not in neutral.edges
    assert "likes:coffee" not in emotional.edges


def test_identity_sticky_false_reverts_decay_drop_behavior():
    cfg = replace(DEFAULT, identity_sticky=False)
    svc = FernService(store=SQLiteStore(":memory:"), cfg=cfg)
    svc.consent("s", "u", True)
    svc.observe("s", "u", "chat", {"tags": ["company:acme"]})
    ug = svc.store.load_user("s", "u")

    for t in range(1, 91):
        decay(ug, now=float(t), cfg=cfg)

    assert "company:acme" not in ug.edges


def test_card_excludes_style_and_mood_noise():
    ug = UserGraph("s", "u")
    ag = AssocGraph("s")
    ug.edges["style:medium"] = Edge(weight=9.0, confidence=1.0, hits=10)
    ug.edges["mood:frustrated"] = Edge(weight=9.0, confidence=1.0, hits=10)
    ug.edges["company:acme"] = Edge(weight=2.0, confidence=0.8, hits=1,
                                    salience=DEFAULT.salience_identity)
    ug.numeric["mood_ema"] = -0.5
    ug.numeric["mood_prev"] = 0.1
    ug.numeric["budget"] = 10

    card = compile_card(ug, ag, [], 0.0, cfg=DEFAULT)

    assert "company:acme" in card["wire"]
    assert "style:" not in card["wire"]
    assert "mood:" not in card["wire"]
    assert "mood_ema" not in card["wire"]
    assert "mood_prev" not in card["wire"]
    assert card["numeric"] == {"budget": 10}


def test_card_salience_surfaces_identity_fact():
    ug = UserGraph("s", "u")
    ag = AssocGraph("s")
    cfg = replace(DEFAULT, top_n=3)
    ug.edges["style:verbose"] = Edge(weight=9.0, confidence=1.0, hits=20)
    ug.edges["style:medium"] = Edge(weight=9.0, confidence=1.0, hits=20)
    ug.edges["topic:a"] = Edge(weight=2.0, confidence=0.8, hits=1)
    ug.edges["topic:b"] = Edge(weight=2.0, confidence=0.8, hits=1)
    ug.edges["topic:c"] = Edge(weight=2.0, confidence=0.8, hits=1)
    ug.edges["company:acme"] = Edge(weight=1.25, confidence=0.5, hits=1,
                                    salience=cfg.salience_identity)

    card = compile_card(ug, ag, ["where do I work?"], 0.0, cfg=cfg)

    assert "company:acme" in card["wire"]
    assert "style:" not in card["wire"]


def test_dogfood_identity_sequence_surfaces_work_and_drops_style_noise():
    svc = FernService(store=SQLiteStore(":memory:"))
    svc.consent("s", "u", True)
    svc.observe("s", "u", "chat", {
        "tags": [
            "company:acme",
            "affiliation:state-university",
            "position:professor-state-university",
        ],
        "text": "I work at Acme and I am a research professor at State University.",
    })
    for i in range(6):
        svc.observe("s", "u", "chat", {
            "tags": [f"pref:coffee-{i}"],
            "text": "I like coffee.",
        })

    card = svc.card("s", "u", context=["who am I?", "where do I work?"])

    assert "company:acme" in card["wire"]
    assert ("affiliation:state-university" in card["wire"]
            or "position:professor-state-university" in card["wire"])
    assert "style:" not in card["wire"]
    assert "mood_" not in card["wire"]


def test_superseded_identity_is_not_locked_in_by_salience():
    cfg = replace(DEFAULT, curation=True)
    svc = FernService(store=SQLiteStore(":memory:"), cfg=cfg)
    svc.consent("s", "u", True)
    svc.observe("s", "u", "chat", {
        "tags": ["company:oldco"],
        "source": "stated",
        "text": "I work at OldCo.",
    }, ts=1.0)
    svc.observe("s", "u", "chat", {
        "tags": ["company:newco"],
        "source": "stated",
        "text": "I now work at NewCo.",
    }, ts=2.0)

    ug = svc.store.load_user("s", "u")
    assert ug.edges["company:oldco"].source == "superseded"
    card = svc.card("s", "u", context=["where do I work?"])
    assert "company:newco" in card["wire"]
    assert "company:oldco" not in card["wire"]

    ug = svc.store.load_user("s", "u")
    for t in range(3, 366):
        decay(ug, now=float(t), cfg=cfg)
    assert "company:oldco" not in ug.edges
    assert "company:newco" in ug.edges


def test_negative_edges_get_salience_floor():
    cfg = DEFAULT
    ug = UserGraph("s","u"); ag = AssocGraph("s")
    observe(ug, ag, Event("s","u",0.0,"v",{}), [("!pref:mushrooms", 5.0)], cfg)
    assert ug.edges["!pref:mushrooms"].salience >= cfg.salience_neg


def test_outcome_adds_salience():
    svc = FernService(store=SQLiteStore(":memory:"))
    svc.store.set_consent("s","u",True)
    svc.observe("s","u","view",{"tags":["pref:plan"]})
    svc.record_outcome("s","u", success=False, attrs=["pref:plan"], weight=1.0)
    e = svc.store.load_user("s","u").edges["pref:plan"]
    assert e.salience > 0   # a failed outcome is memorable


def test_salience_persists_round_trip():
    st = SQLiteStore(":memory:")
    svc = FernService(store=st); svc.store.set_consent("s","u",True)
    svc.observe("s","u","view",{"tags":["pref:x"],"intensity":0.8})
    e = svc.store.load_user("s","u").edges["pref:x"]
    assert abs(e.salience - 0.8) < 1e-6        # survived save->load
