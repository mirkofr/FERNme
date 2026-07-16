"""Canonical entity-kind vocabulary.

Tag namespaces may be arbitrary. Entity kinds are not: unknown surfaces collapse
to ``other`` unless they have an explicit alias here.
"""
from __future__ import annotations

ENTITY_KINDS = frozenset({"person", "org", "project", "place", "thing", "other"})
ANY_KIND = frozenset(ENTITY_KINDS)

ENTITY_KIND_ALIASES = {
    "company": "org",
    "organization": "org",
    "organisation": "org",
    "institution": "org",
    "team": "org",
    "people": "person",
    "human": "person",
    "user": "person",
    "owner": "person",
    "location": "place",
    "city": "place",
    "country": "place",
    "product": "thing",
    "object": "thing",
}


def canonical_entity_kind(value: object) -> str:
    raw = str(value or "").strip().lower().replace("_", "-")
    if raw in ENTITY_KINDS:
        return raw
    return ENTITY_KIND_ALIASES.get(raw, "other")


def is_canonical_entity_kind(value: object) -> bool:
    return str(value or "").strip().lower() in ENTITY_KINDS
