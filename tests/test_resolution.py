"""Resolution-derived decay: flat-path compatibility and v0 behavior."""
import math
import sys, os
from dataclasses import replace

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from fernme.config import DEFAULT
from fernme.core.graph import UserGraph, Edge
from fernme.resolution import lambda_eff, phase, species_of, temperature
from fernme.write.hebbian import decay


def test_resolution_flag_off_preserves_existing_decay_math():
    cfg = replace(DEFAULT, resolution=False, salience_beta=0.5)
    ug = UserGraph("s", "u")
    ug.edges["pref:x"] = Edge(weight=5.0, confidence=0.9, source="known",
                              last_reinforced=0.0, hits=3, fast=3.0,
                              salience=0.8)

    decay(ug, now=10.0, cfg=cfg, conflict_map={"pref:x": 1.0})

    expected_lam = cfg.lam * (1.0 - cfg.salience_beta * 0.8)
    assert math.isclose(ug.edges["pref:x"].weight,
                        5.0 * math.exp(-expected_lam * 10.0))
    assert ug.edges["pref:x"].last_reinforced == 10.0


def test_non_override_keeps_positive_decay_floor():
    cfg = replace(DEFAULT, resolution=True)
    edge = Edge(weight=9.0, confidence=1.0, source="known",
                last_reinforced=0.0, hits=10, provenance="stated")

    lam = lambda_eff("pref:concise", edge, {"now": 0.0}, 0.0, cfg)

    assert lam > 0.0
    assert math.isclose(temperature("pref:concise", edge, 0.0, cfg,
                                    {"now": 0.0}),
                        cfg.temperature_floor_non_override)
    assert phase("pref:concise", edge, cfg, {"now": 0.0}) == "crystal"


def test_override_still_never_decays_when_resolution_enabled():
    cfg = replace(DEFAULT, resolution=True)
    ug = UserGraph("s", "u")
    ug.edges["pref:locked"] = Edge(weight=5.0, confidence=1.0,
                                   source="override", last_reinforced=0.0,
                                   hits=1)

    decay(ug, now=10000.0, cfg=cfg, conflict_map={"pref:locked": 1.0})

    assert ug.edges["pref:locked"].weight == 5.0
    assert phase("pref:locked", ug.edges["pref:locked"], cfg,
                 {"now": 10000.0}) == "locked"


def test_conflict_heat_accelerates_decay():
    cfg = replace(DEFAULT, resolution=True)
    cool = UserGraph("s", "u")
    hot = UserGraph("s", "u")
    edge = Edge(weight=9.0, confidence=1.0, source="known",
                last_reinforced=0.0, hits=10, provenance="stated")
    cool.edges["diet:vegetarian"] = Edge(**edge.__dict__)
    hot.edges["diet:vegetarian"] = Edge(**edge.__dict__)

    decay(cool, now=100.0, cfg=cfg)
    decay(hot, now=100.0, cfg=cfg, conflict_map={"diet:vegetarian": 1.0})

    hot_weight = hot.edges["diet:vegetarian"].weight if "diet:vegetarian" in hot.edges else 0.0
    assert hot_weight < cool.edges["diet:vegetarian"].weight


def test_species_lookup_is_attr_aware():
    assert species_of("name:elena") == "permanent"
    assert species_of("allergy:peanut") == "permanent"
    assert species_of("health:asthma") == "permanent"
    assert species_of("employer:acme") == "slow"
    assert species_of("project:fernme") == "volatile"
    assert species_of("habit:cli") == "habit"
    assert species_of("style:concise") == "style"
    assert species_of("!likes:coffee") == "preference"
