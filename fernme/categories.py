"""Deterministic memory categories — a reproducible, namespace-driven grouping.

FERNme stores each memory as a fine-grained `namespace:value` attribute (pref:, rel:,
goal:, topic:, ...). This module rolls those namespaces up into a small, stable set of
coarse CATEGORIES used by clients and the memory-map visualization. It is a pure lookup
table: no LLM, no per-user state, identical for everyone. Dislikes (negative edges) map
to the 'emotional' category regardless of namespace.
"""
from __future__ import annotations

# Coarse categories, in display order. Colors are presentation hints clients may use.
CATEGORIES = [
    {"key": "values",    "label": "Values & goals",      "color": "#a8690b"},
    {"key": "people",    "label": "People",              "color": "#185fa5"},
    {"key": "facts",     "label": "Facts & identity",    "color": "#0f6e56"},
    {"key": "habits",    "label": "Habits & skills",     "color": "#6d4bb0"},
    {"key": "media",     "label": "Media & sensory",     "color": "#2f8f4e"},
    {"key": "emotional", "label": "Emotional / dislikes","color": "#a32d2d"},
]

DEFAULT_CATEGORY = "facts"

# namespace -> category. Extend freely; unknown namespaces fall back to DEFAULT_CATEGORY.
_NS_TO_CAT = {
    "value": "values", "goal": "values", "pref": "values",
    "rel": "people",
    "name": "facts", "nickname": "facts", "birthday": "facts", "city": "facts",
    "origin": "facts", "field": "facts", "study": "facts", "topic": "facts",
    "employer": "facts", "role": "facts", "status": "facts", "metric": "facts",
    "project": "facts", "health": "facts", "domain": "facts", "context": "facts",
    "habit": "habits", "activity": "habits", "trait": "habits", "style": "habits",
    "comm": "habits", "phrase": "habits",
    "media": "media", "brand": "media", "food": "media", "tea": "media",
    "music": "media", "movie": "media", "book": "media", "pet": "media", "entity": "media",
}


def namespace_of(attr: str) -> str:
    base = attr.lstrip("!")
    return base.split(":", 1)[0] if ":" in base else "attr"


def category_of(attr: str) -> str:
    """Map an attribute (e.g. 'pref:flat-white' or '!pref:dairy') to a coarse category.
    Dislikes (leading '!') are 'emotional'; otherwise by namespace."""
    if attr.startswith("!"):
        return "emotional"
    return _NS_TO_CAT.get(namespace_of(attr), DEFAULT_CATEGORY)
