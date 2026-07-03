import json
import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from fernme.relations import (
    DEFAULT_RELATIONS,
    RELATION_ALIASES,
    RELATIONS,
    REVERSED_SURFACES,
    RelationVocabulary,
    canonical_pair,
    inverse_names,
)
from fernme.service import FernService


def _svc():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    os.remove(path)
    svc = FernService(path)
    svc.consent("demo", "alex", True)
    return svc, path


def test_relation_alias_targets_are_canonical():
    assert RELATION_ALIASES
    for canonical in RELATION_ALIASES.values():
        assert canonical in RELATIONS


def test_reversed_surface_buys_from_rejects_with_swap_guidance():
    svc, _ = _svc()
    orbit = svc.entity_create("demo", "alex", "org", "Orbit Labs")
    northwind = svc.entity_create("demo", "alex", "org", "Northwind Ltd")

    with pytest.raises(ValueError, match="selling_to.*swapped"):
        DEFAULT_RELATIONS.resolve("buys_from")
    with pytest.raises(ValueError, match="selling_to.*swapped"):
        svc.entity_relate("demo", "alex", orbit, "buys_from", northwind)

    assert REVERSED_SURFACES["buys_from"] == "selling_to"
    assert "buys_from" not in RELATION_ALIASES


def test_alias_table_does_not_contain_direction_reversing_surfaces():
    intended = {
        "employed_by": ({"person"}, {"org"}),
        "employee_of": ({"person"}, {"org"}),
        "job_at": ({"person"}, {"org"}),
        "founder_of": ({"person"}, {"org"}),
        "boss_of": ({"person"}, {"org", "project"}),
        "leads": ({"person"}, {"org", "project"}),
        "married_to": ({"person"}, {"person"}),
        "parent_of": ({"person"}, {"person"}),
        "child_of": ({"person"}, {"person"}),
        "sibling_of": ({"person"}, {"person"}),
        "coworker_of": ({"person"}, {"person"}),
        "connected_to": (set(RELATIONS["related_to"].subject_kinds),
                         set(RELATIONS["related_to"].object_kinds)),
        "linked_to": (set(RELATIONS["related_to"].subject_kinds),
                      set(RELATIONS["related_to"].object_kinds)),
    }

    assert set(RELATION_ALIASES) == set(intended)
    for alias, canonical in RELATION_ALIASES.items():
        spec = RELATIONS[canonical]
        subject_kinds, object_kinds = intended[alias]
        # Direction-changing aliases are forbidden: alias(subject, object) must
        # be valid as canonical(subject, object), with no hidden argument swap.
        assert subject_kinds <= spec.subject_kinds
        assert object_kinds <= spec.object_kinds


def test_inverse_names_are_read_only_write_surfaces():
    inverses = inverse_names(DEFAULT_RELATIONS.relations)
    assert {"led_by", "employs", "buying_from"} <= inverses
    for inverse in inverses:
        with pytest.raises(ValueError, match="read-only"):
            DEFAULT_RELATIONS.resolve(inverse)


def test_symmetric_canonical_pair_is_stable():
    a = "11111111-1111-4111-8111-111111111111"
    b = "22222222-2222-4222-8222-222222222222"

    assert canonical_pair(a, "friend_of", b) == canonical_pair(b, "friend_of", a)


def test_unknown_relation_and_kind_mismatch_reject():
    svc, _ = _svc()
    dana = svc.entity_create("demo", "alex", "person", "Dana Reyes")
    northwind = svc.entity_create("demo", "alex", "org", "Northwind Ltd")

    with pytest.raises(ValueError, match="unknown relation"):
        svc.entity_relate("demo", "alex", dana, "ignore_previous", northwind)
    with pytest.raises(ValueError, match="allows subjects"):
        svc.entity_relate("demo", "alex", northwind, "ceo_of", dana)


def test_json_extension_loads_and_resolves_alias():
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump({
                "relations": {
                    "mentors": ["mentored_by", False, ["person"], ["person"]],
                },
                "aliases": {"advisor_of": "mentors"},
            }, f)

        vocab = RelationVocabulary.from_json(path)

        assert vocab.resolve("advisor_of") == "mentors"
        assert vocab.validate_kinds("mentors", "person", "person") == "mentors"
    finally:
        os.remove(path)


def test_alias_resolution_at_entity_relate_boundary():
    svc, _ = _svc()
    dana = svc.entity_create("demo", "alex", "person", "Dana Reyes")
    northwind = svc.entity_create("demo", "alex", "org", "Northwind Ltd")

    row = svc.entity_relate("demo", "alex", dana, "founder_of", northwind)

    assert row["relation"] == "ceo_of"
    assert len(svc.store.list_entity_relations("demo", "alex")) == 1


def test_symmetric_alias_resolution_is_unchanged():
    svc, _ = _svc()
    dana = svc.entity_create("demo", "alex", "person", "Dana Reyes")
    felix = svc.entity_create("demo", "alex", "person", "Felix Tan")

    married = svc.entity_relate("demo", "alex", dana, "married_to", felix)
    coworker = svc.entity_relate("demo", "alex", felix, "coworker_of", dana)

    assert married["relation"] == "family_of"
    assert coworker["relation"] == "colleague_of"
    assert len(svc.store.list_entity_relations("demo", "alex")) == 2


def test_related_to_accepts_any_kind_pair():
    svc, _ = _svc()
    place = svc.entity_create("demo", "alex", "place", "Harbor District")
    thing = svc.entity_create("demo", "alex", "thing", "Sample Kit")

    row = svc.entity_relate("demo", "alex", place, "related_to", thing)

    assert row["relation"] == "related_to"


def test_path_ranking_prefers_typed_relation_over_related_to_at_equal_weight():
    svc, _ = _svc()
    dana = svc.entity_create("demo", "alex", "person", "Dana Reyes")
    northwind = svc.entity_create("demo", "alex", "org", "Northwind Ltd")
    svc.entity_relate("demo", "alex", dana, "related_to", northwind)
    svc.entity_relate("demo", "alex", dana, "ceo_of", northwind)

    paths = svc.recall_path("demo", "alex", dana, northwind)

    assert paths[0][0]["relation"] == "ceo_of"
