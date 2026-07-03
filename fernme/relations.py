"""Controlled relation vocabulary for the typed entity layer."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, Tuple

ENTITY_KINDS = {"person", "org", "project", "place", "thing", "other"}
ANY_KIND = frozenset(ENTITY_KINDS)


@dataclass(frozen=True)
class RelationSpec:
    inverse: str
    symmetric: bool
    subject_kinds: frozenset[str]
    object_kinds: frozenset[str]


RELATIONS: Dict[str, RelationSpec] = {
    "knows":        RelationSpec("knows",         True,  frozenset({"person"}),        frozenset({"person"})),
    "contact_of":   RelationSpec("contact_of",    True,  frozenset({"person"}),        frozenset({"person", "org"})),
    "family_of":    RelationSpec("family_of",     True,  frozenset({"person"}),        frozenset({"person"})),
    "friend_of":    RelationSpec("friend_of",     True,  frozenset({"person"}),        frozenset({"person"})),
    "colleague_of": RelationSpec("colleague_of",  True,  frozenset({"person"}),        frozenset({"person"})),
    "ceo_of":       RelationSpec("led_by",        False, frozenset({"person"}),        frozenset({"org"})),
    "works_at":     RelationSpec("employs",       False, frozenset({"person"}),        frozenset({"org"})),
    "manager_of":   RelationSpec("managed_by",    False, frozenset({"person"}),        frozenset({"org", "project"})),
    "member_of":    RelationSpec("has_member",    False, frozenset({"person"}),        frozenset({"org", "project"})),
    "owns":         RelationSpec("owned_by",      False, frozenset({"person", "org"}), frozenset({"org", "project", "thing"})),
    "part_of":      RelationSpec("has_part",      False, frozenset({"org", "project"}), frozenset({"org", "project"})),
    "located_in":   RelationSpec("location_of",   False, frozenset({"person", "org", "project"}), frozenset({"place"})),
    "works_on":     RelationSpec("worked_on_by",  False, frozenset({"person", "org"}), frozenset({"project"})),
    "helping_with": RelationSpec("helped_by",     False, frozenset({"person", "org"}), frozenset({"project", "org"})),
    "selling_to":   RelationSpec("buying_from",   False, frozenset({"org", "person"}), frozenset({"org", "person", "place"})),
    "supplies":     RelationSpec("supplied_by",   False, frozenset({"org"}),           frozenset({"org", "project"})),
    "related_to":   RelationSpec("related_to",    True,  ANY_KIND,                     ANY_KIND),
}

RELATION_ALIASES = {
    "employed_by": "works_at", "employee_of": "works_at", "job_at": "works_at",
    "founder_of": "ceo_of",
    "boss_of": "manager_of", "leads": "manager_of",
    "married_to": "family_of", "parent_of": "family_of", "child_of": "family_of",
    "sibling_of": "family_of",
    "coworker_of": "colleague_of",
    "buys_from": "selling_to",
    "connected_to": "related_to", "linked_to": "related_to",
}


class RelationVocabulary:
    def __init__(self, relations=None, aliases=None):
        self.relations = dict(relations or RELATIONS)
        self.aliases = dict(aliases or RELATION_ALIASES)
        self._validate()

    @classmethod
    def from_json(cls, path: str | Path) -> "RelationVocabulary":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        relations = dict(RELATIONS)
        for name, spec in data.get("relations", {}).items():
            inverse, symmetric, subject, obj = spec
            relations[name] = RelationSpec(
                str(inverse), bool(symmetric), frozenset(subject), frozenset(obj)
            )
        aliases = dict(RELATION_ALIASES)
        aliases.update(data.get("aliases", {}))
        return cls(relations, aliases)

    def _validate(self) -> None:
        for name, spec in self.relations.items():
            if spec.inverse != name and spec.inverse in self.relations:
                inverse = self.relations[spec.inverse]
                if inverse.inverse != name:
                    raise ValueError(f"inverse mismatch for {name}")
            if not spec.subject_kinds <= ENTITY_KINDS:
                raise ValueError(f"unknown subject kinds for {name}")
            if not spec.object_kinds <= ENTITY_KINDS:
                raise ValueError(f"unknown object kinds for {name}")
        for alias, canonical in self.aliases.items():
            if canonical not in self.relations:
                raise ValueError(f"relation alias {alias} targets unknown {canonical}")

    def resolve(self, relation: str) -> str:
        if relation in inverse_names(self.relations):
            allowed = ", ".join(sorted(self.relations))
            raise ValueError(f"inverse relation {relation} is read-only; allowed: {allowed}")
        canonical = self.aliases.get(relation, relation)
        if canonical not in self.relations:
            allowed = ", ".join(sorted(self.relations))
            raise ValueError(f"unknown relation {relation}; allowed: {allowed}")
        return canonical

    def spec(self, relation: str) -> RelationSpec:
        return self.relations[self.resolve(relation)]

    def validate_kinds(self, relation: str, subject_kind: str, object_kind: str) -> str:
        canonical = self.resolve(relation)
        spec = self.relations[canonical]
        if subject_kind not in spec.subject_kinds or object_kind not in spec.object_kinds:
            raise ValueError(
                f"{canonical} allows subjects {sorted(spec.subject_kinds)} "
                f"and objects {sorted(spec.object_kinds)}"
            )
        return canonical


DEFAULT_RELATIONS = RelationVocabulary()


def inverse_names(relations=None) -> set[str]:
    rels = relations or RELATIONS
    return {spec.inverse for name, spec in rels.items() if spec.inverse != name}


def canonical_pair(subject_id: str, relation: str, object_id: str,
                   vocab: RelationVocabulary = DEFAULT_RELATIONS) -> Tuple[str, str, str]:
    canonical = vocab.resolve(relation)
    spec = vocab.relations[canonical]
    if spec.symmetric and object_id < subject_id:
        return object_id, canonical, subject_id
    return subject_id, canonical, object_id


def relation_sort_key(row: dict) -> tuple:
    typed = 1 if row["relation"] == "related_to" else 0
    return (typed, -float(row.get("weight", 0.0)), row["relation"], row["object_id"])
