import json
import os
import sys
import tempfile
from dataclasses import replace

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from fernme.config import DEFAULT
from fernme.core.graph import Edge
from fernme.retrieve.entity_card import aggregate_entity_activation, card_token_estimate
from fernme.service import FernService


def _db_path():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    os.remove(path)
    return path


def _svc(cfg=DEFAULT):
    path = _db_path()
    svc = FernService(path, cfg=cfg)
    svc.consent("demo", "alex", True)
    return svc


def _rank(card, attr):
    attrs = [row["attr"] for row in card["links"]]
    return attrs.index(attr) if attr in attrs else 999


def _rank_any(card, attrs):
    return min((_rank(card, attr) for attr in attrs), default=999)


def _observe_many(svc, attr, n):
    for i in range(n):
        svc.observe("demo", "alex", "note", {"tags": [attr]}, ts=0.0 + i * 0.001)


def _link_dana_entity(svc):
    dana = svc.entity_create("demo", "alex", "person", "Dana Reyes")
    for alias in ("person:dana", "person:dana-reyes", "person:mrs-reyes"):
        svc.entity_link_alias("demo", "alex", dana, alias)
    return dana


def _build_dilution_fixture(fragmented, cfg):
    svc = _svc(cfg)
    if fragmented:
        for alias in ("person:dana", "person:dana-reyes", "person:mrs-reyes"):
            _observe_many(svc, alias, 3)
    else:
        _observe_many(svc, "person:dana", 9)
    _observe_many(svc, "topic:orbit", 4)
    _link_dana_entity(svc)
    return svc


def _build_enrichment_fixture(cfg):
    svc = _svc(cfg)
    for alias in ("person:dana", "person:dana-reyes", "person:mrs-reyes"):
        _observe_many(svc, alias, 2)
    _observe_many(svc, "org:northwind", 2)
    for attr in ("topic:orbit", "pref:quiet", "goal:pilot", "context:demo"):
        _observe_many(svc, attr, 1)
    dana = _link_dana_entity(svc)
    northwind = svc.entity_create("demo", "alex", "org", "Northwind Ltd")
    svc.entity_link_alias("demo", "alex", northwind, "org:northwind")
    svc.entity_set_field("demo", "alex", dana, "phone", "555-0101")
    svc.entity_set_field("demo", "alex", dana, "note", "fictional contact")
    svc.entity_relate("demo", "alex", dana, "ceo_of", northwind,
                      note="founded team", provenance="stated", ts=1.0)
    return svc


def test_aggregate_entity_activation_sums_aliases_and_chooses_highest_weight_alias():
    out = aggregate_entity_activation(
        {"person:dana": 0.5, "person:dana-reyes": 0.75, "topic:orbit": 2.0},
        {"person:dana": "e1", "person:dana-reyes": "e1"},
        {"e1": ["person:dana", "person:dana-reyes"]},
        {"person:dana": 4.0, "person:dana-reyes": 2.0},
    )

    assert out["e1"]["activation"] == 1.25
    assert out["e1"]["representative"] == "person:dana"


def test_entity_aggregation_fixes_fragmented_alias_dilution():
    off_cfg = replace(DEFAULT, top_n=1)
    on_cfg = replace(DEFAULT, top_n=1, entity_aggregation=True)
    fragmented_off = _build_dilution_fixture(fragmented=True, cfg=off_cfg)
    concentrated_off = _build_dilution_fixture(fragmented=False, cfg=off_cfg)
    fragmented_on = _build_dilution_fixture(fragmented=True, cfg=on_cfg)

    fragmented_off_card = fragmented_off.card("demo", "alex", now=0.0)
    concentrated_card = concentrated_off.card("demo", "alex", now=0.0)
    aggregated_card = fragmented_on.card("demo", "alex", now=0.0)

    assert fragmented_off_card["links"][0]["attr"] == "topic:orbit"
    assert concentrated_card["links"][0]["attr"] == "person:dana"
    assert aggregated_card["links"][0]["attr"] == "person:dana"
    assert _rank(aggregated_card, "person:dana") <= _rank(concentrated_card, "person:dana")


def test_entity_aggregation_never_demotes_boundary_person_with_distractors():
    aliases = [f"person:fictional-alias-{i}" for i in range(8)]
    off_cfg = replace(DEFAULT, top_n=12)
    on_cfg = replace(DEFAULT, top_n=12, entities=True, entity_aggregation=True)
    svc = _svc(off_cfg)
    ug = svc.store.load_user("demo", "alex")

    for i in range(10):
        ug.edges[f"distractor{i}:strong"] = Edge(weight=DEFAULT.w_max, confidence=1.0, hits=20)
    for i in range(5):
        ug.edges[f"distractor_mid{i}:strong"] = Edge(weight=2.2, confidence=1.0, hits=10)
    for alias, weight in zip(aliases, (3.0, 2.8, 2.5, 2.2, 2.0, 1.8, 1.5, 1.2)):
        ug.edges[alias] = Edge(weight=weight, confidence=1.0, hits=8)
    svc.store.save_user(ug)

    entity = svc.entity_create("demo", "alex", "person", "Alexandria Fictional Longname Demo")
    for alias in aliases:
        svc.entity_link_alias("demo", "alex", entity, alias)

    off_card = svc.card("demo", "alex", now=0.0)
    svc.cfg = on_cfg
    on_card = svc.card("demo", "alex", now=0.0)

    off_rank = _rank_any(off_card, aliases)
    on_rank = _rank_any(on_card, aliases)
    assert off_rank == 10
    assert on_rank <= off_rank


def test_entity_card_enriches_with_fields_and_active_stated_neighbor_within_budget():
    plain_cfg = replace(DEFAULT, top_n=8)
    enriched_cfg = replace(DEFAULT, top_n=8, entities=True, entity_aggregation=True)
    plain = _build_enrichment_fixture(plain_cfg).card("demo", "alex", now=0.0)
    enriched = _build_enrichment_fixture(enriched_cfg).card("demo", "alex", now=0.0)

    assert "entity:Dana Reyes" in enriched["wire"]
    assert "phone:555-0101" in enriched["wire"]
    assert "ceo_of->Northwind Ltd(founded team)" in enriched["wire"]
    assert "card_token_estimate" in enriched
    assert enriched["card_token_estimate"] <= card_token_estimate(plain["wire"])


def test_entity_card_is_deterministic_for_same_fixture():
    cfg = replace(DEFAULT, top_n=8, entities=True, entity_aggregation=True)
    first = _build_enrichment_fixture(cfg).card("demo", "alex", now=0.0)
    second = _build_enrichment_fixture(cfg).card("demo", "alex", now=0.0)

    assert json.dumps(first, sort_keys=True, separators=(",", ":")) == json.dumps(
        second, sort_keys=True, separators=(",", ":")
    )
