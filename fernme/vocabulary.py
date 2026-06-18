"""Controlled, namespaced vocabulary — the ingestion bridge's consistency layer.

THE foundation that can't be retrofitted: if the same concept is tagged
`written_steps` one day and `prefers_written` the next, that drift is baked into
history forever. The Vocabulary normalizes every tag (from catalog, free text, or
LLM) to ONE canonical `namespace:value` form, so a concept always lands on the same
edge over months. Namespaces (`pref:`, `topic:`, `goal:`, `context:`, `domain:`)
also double as the natural raw material for a future recursive/region layer."""
from __future__ import annotations
import re
from typing import Dict, List, Optional, Sequence


def _key(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")


class Vocabulary:
    def __init__(self, default_namespace: str = "pref", strict: bool = False):
        self.terms: set[str] = set()        # canonical "ns:value"
        self.aliases: Dict[str, str] = {}   # normalized raw -> canonical
        self.default_namespace = default_namespace
        self.strict = strict                # strict: drop unknowns; lenient: namespace them

    def add(self, canonical: str, aliases: Sequence[str] = ()):
        if ":" not in canonical:
            canonical = f"{self.default_namespace}:{_key(canonical)}"
        self.terms.add(canonical)
        ns, val = canonical.split(":", 1)
        # the canonical, its bare value, and every alias all resolve to canonical
        for a in (canonical, val, *aliases):
            self.aliases[_key(a)] = canonical
        return self

    @classmethod
    def from_spec(cls, spec: Dict[str, Sequence[str]], **kw) -> "Vocabulary":
        v = cls(**kw)
        for canonical, aliases in spec.items():
            v.add(canonical, aliases)
        return v

    def canonical(self, tag: str) -> Optional[str]:
        k = _key(tag)
        if k in self.aliases:
            return self.aliases[k]
        if tag in self.terms:
            return tag
        if self.strict:
            return None                      # unknown -> dropped
        if ":" in tag:                       # already namespaced (e.g. style:formal) -> keep
            return tag
        return f"{self.default_namespace}:{k}"  # lenient: give it the default namespace

    def normalize(self, tags) -> List[str]:
        out: List[str] = []
        for t in tags or []:
            c = self.canonical(t)
            if c and c not in out:
                out.append(c)
        return out
