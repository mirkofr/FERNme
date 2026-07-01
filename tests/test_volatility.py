"""Volatility-typed memory behavior. Run: pytest -q tests/test_volatility.py"""
import math
import sys, os
from dataclasses import replace

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from fernme.config import DEFAULT
from fernme.core.graph import UserGraph, AssocGraph, Event, Edge
from fernme.retrieve.card import compile_card
from fernme.write.hebbian import observe, decay
from fernme.confidence import compute
from fernme.resolution import needs_verify, species_multiplier


def test_observe_preserves_stated_and_inferred_provenance():
    cfg = DEFAULT
    ug = UserGraph("s", "u")
    ag = AssocGraph("s")

    observe(ug, ag, Event("s", "u", 0.0, "chat", {}), [("name:elena", 1.0)],
            cfg, provenance="stated")
    observe(ug, ag, Event("s", "u", 1.0, "chat", {}), [("project:atlas", 1.0)],
            cfg, provenance="inferred")
    observe(ug, ag, Event("s", "u", 2.0, "chat", {}), [("name:elena", 1.0)],
            cfg, provenance="inferred")

    assert ug.edges["name:elena"].provenance == "stated"
    assert ug.edges["project:atlas"].provenance == "inferred"


def test_species_decay_is_derived_from_half_lives():
    cfg = replace(DEFAULT, volatility_half_lives={
        **DEFAULT.volatility_half_lives,
        "volatile": 3.5,
    })

    assert math.isclose(cfg.species_decay["volatile"], species_multiplier("project:x", cfg))
    assert cfg.species_decay["volatile"] > DEFAULT.species_decay["volatile"]


def test_volatility_decay_is_flagged_and_class_specific():
    off = replace(DEFAULT, resolution=False, floor=0.0)
    on = replace(DEFAULT, resolution=True, floor=0.0)
    stable = UserGraph("s", "stable")
    volatile = UserGraph("s", "volatile")
    stable.edges["name:elena"] = Edge(weight=5.0, hits=5, last_reinforced=0.0,
                                      provenance="stated")
    volatile.edges["project:atlas"] = Edge(weight=5.0, hits=5, last_reinforced=0.0)

    decay(stable, now=60.0, cfg=on)
    decay(volatile, now=60.0, cfg=on)

    flat_expected = 5.0 * math.exp(-off.lam * 60.0)
    assert stable.edges["name:elena"].weight > flat_expected
    assert volatile.edges["project:atlas"].weight < flat_expected


def test_volatility_confidence_ages_volatile_facts_faster():
    edge = Edge(weight=5.0, confidence=0.9, source="known",
                last_reinforced=0.0, hits=5)
    flat = compute(edge, 30.0, replace(DEFAULT, volatility_confidence=False),
                   attr="project:atlas")
    volatile = compute(edge, 30.0, replace(DEFAULT, volatility_confidence=True),
                       attr="project:atlas")

    assert volatile < flat


def test_confidence_volatility_never_boosts_middle_classes():
    edge = Edge(weight=5.0, confidence=0.9, source="known",
                last_reinforced=0.0, hits=5)
    flat = compute(edge, 180.0, replace(DEFAULT, volatility_confidence=False),
                   attr="pref:long-emails")
    middle = compute(edge, 180.0, replace(DEFAULT, volatility_confidence=True),
                     attr="pref:long-emails")
    permanent = compute(edge, 180.0, replace(DEFAULT, volatility_confidence=True),
                        attr="allergy:peanut")

    assert middle <= flat
    assert permanent > flat


def test_volatility_confidence_and_resolution_flags_are_independent():
    edge = Edge(weight=5.0, confidence=0.9, source="known",
                last_reinforced=0.0, hits=5)
    cfg_conf_only = replace(DEFAULT, resolution=False, volatility_confidence=True,
                            verify_age_enabled=True, floor=0.0)
    cfg_decay_only = replace(DEFAULT, resolution=True, volatility_confidence=False,
                             floor=0.0)

    flat_conf = compute(edge, 30.0, replace(DEFAULT, volatility_confidence=False),
                        attr="project:atlas")
    vol_conf = compute(edge, 30.0, cfg_conf_only, attr="project:atlas")
    assert vol_conf < flat_conf
    assert needs_verify("project:atlas", edge, 30.0, cfg_conf_only)["verify"]

    flat = UserGraph("s", "flat")
    classed = UserGraph("s", "classed")
    flat.edges["project:atlas"] = Edge(weight=5.0, hits=5, last_reinforced=0.0)
    classed.edges["project:atlas"] = Edge(weight=5.0, hits=5, last_reinforced=0.0)
    decay(flat, now=30.0, cfg=replace(DEFAULT, resolution=False, floor=0.0))
    decay(classed, now=30.0, cfg=cfg_decay_only)
    assert classed.edges["project:atlas"].weight < flat.edges["project:atlas"].weight

    unchanged_conf = compute(edge, 30.0, cfg_decay_only, attr="project:atlas")
    assert math.isclose(unchanged_conf, flat_conf)


def test_verify_signal_for_fresh_stale_override_and_permanent():
    cfg = replace(DEFAULT, volatility_confidence=True, verify_age_enabled=True)
    fresh = Edge(weight=5.0, confidence=0.9, last_reinforced=0.0, hits=5)
    stale = Edge(weight=5.0, confidence=0.9, last_reinforced=0.0, hits=5)
    locked = Edge(weight=5.0, confidence=1.0, source="override",
                  last_reinforced=0.0, hits=1)
    permanent = Edge(weight=5.0, confidence=0.9, last_reinforced=0.0, hits=5,
                     provenance="stated")

    assert not needs_verify("project:atlas", fresh, 5.0, cfg)["verify"]
    assert needs_verify("project:atlas", stale, 30.0, cfg)["verify"]
    assert not needs_verify("project:atlas", locked, 10000.0, cfg)["verify"]
    assert not needs_verify("name:elena", permanent, 365.0, cfg)["verify"]


def test_default_verify_does_not_nag_on_age_alone():
    stale = Edge(weight=5.0, confidence=0.9, last_reinforced=0.0, hits=5)

    detail = needs_verify("project:atlas", stale, 300.0, DEFAULT)

    assert detail["verify"] is False
    assert "age-only verify disabled" in detail["reason"]


def test_high_conflict_edge_requests_verify_even_when_fresh():
    cfg = replace(DEFAULT, volatility_confidence=True, top_n=3)
    edge = Edge(weight=5.0, confidence=0.9, last_reinforced=10.0, hits=5)

    detail = needs_verify("employer:oldco", edge, 11.0, cfg, conflict=0.7)

    assert detail["verify"] is True
    assert detail["reason"].startswith("conflict:")

    ug = UserGraph("s", "u")
    ag = AssocGraph("s")
    ug.edges["employer:oldco"] = edge
    ug.edges["employer:newco"] = Edge(weight=7.0, confidence=0.8,
                                      last_reinforced=12.0, hits=3,
                                      provenance="stated")
    card = compile_card(ug, ag, [], now=11.0, cfg=cfg)
    oldco_link = next(l for l in card["links"] if l["attr"] == "employer:oldco")
    assert oldco_link["verify"] is True


def test_stale_sticky_employer_stays_in_card_but_requests_verify():
    cfg = replace(DEFAULT, volatility_confidence=True, verify_age_enabled=True, top_n=3)
    ug = UserGraph("s", "u")
    ag = AssocGraph("s")
    ug.edges["employer:oldco"] = Edge(weight=DEFAULT.floor, confidence=0.9,
                                      last_reinforced=0.0, hits=5,
                                      salience=DEFAULT.salience_identity,
                                      provenance="stated")

    card = compile_card(ug, ag, ["where do I work?"], now=650.0, cfg=cfg)

    assert "employer:oldco" in card["wire"]
    assert "~verify" in card["wire"]
    assert card["links"][0]["verify"] is True
