"""Controlled, namespaced vocabulary — the ingestion bridge's consistency layer.

THE foundation that can't be retrofitted: if the same concept is tagged
`written_steps` one day and `prefers_written` the next, that drift is baked into
history forever. The Vocabulary normalizes every tag (from catalog, free text, or
LLM) to ONE canonical `namespace:value` form, so a concept always lands on the same
edge over months. Namespaces (`pref:`, `topic:`, `goal:`, `context:`, `domain:`)
also double as the natural raw material for a future recursive/region layer."""
from __future__ import annotations
import json
import re
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple


def _key(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")


def _sanitized_key(s: str) -> str:
    return re.sub(r"[^a-z0-9_:!\-]+", "", s.lower())


class Vocabulary:
    def __init__(self, default_namespace: str = "pref", strict: bool = False):
        self.terms: set[str] = set()        # canonical "ns:value"
        self.aliases: Dict[str, str] = {}   # normalized raw -> canonical
        self.alias_surfaces: Dict[str, str] = {}  # normalized raw -> editable raw
        self.default_namespace = default_namespace
        self.strict = strict                # strict: drop unknowns; lenient: namespace them

    def add(self, canonical: str, aliases: Sequence[str] = ()):
        if ":" not in canonical:
            canonical = f"{self.default_namespace}:{_key(canonical)}"
        self.terms.add(canonical)
        ns, val = canonical.split(":", 1)
        # the canonical, its bare value, and every alias all resolve to canonical
        for a in (canonical, val):
            self.aliases[_key(a)] = canonical
        for a in aliases:
            for k in {_key(a), _key(_sanitized_key(a))}:
                if k:
                    self.aliases[k] = canonical
                    self.alias_surfaces[k] = a
        return self

    @classmethod
    def from_spec(cls, spec: Dict[str, Sequence[str]], **kw) -> "Vocabulary":
        v = cls(**kw)
        for canonical, aliases in spec.items():
            v.add(canonical, aliases)
        return v

    @classmethod
    def from_json(cls, path: str | Path, **kw) -> "Vocabulary":
        """Load an editable canonical -> aliases JSON file."""
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("vocabulary JSON must be an object of canonical -> aliases")
        return cls.from_spec(data, **kw)

    def canonical(self, tag: str) -> Optional[str]:
        if not isinstance(tag, str):
            return None
        neg = tag.startswith("!")
        raw = tag[1:] if neg else tag
        k = _key(raw)
        if k in self.aliases:
            c = self.aliases[k]
            return "!" + c if neg and not c.startswith("!") else c
        if raw in self.terms:
            return "!" + raw if neg else raw
        if self.strict:
            return None                      # unknown -> dropped
        if ":" in raw:                       # already namespaced (e.g. style:formal) -> keep
            return "!" + raw if neg else raw
        c = f"{self.default_namespace}:{k}"  # lenient: give it the default namespace
        return "!" + c if neg else c

    def resolve(self, tag: str) -> Tuple[Optional[str], Optional[str]]:
        """Return (canonical, alias).

        `alias` is the original tag only when it resolves to a different
        canonical edge. Callers can preserve source variants in the Cabinet
        without storing them as separate active graph edges.
        """
        canonical = self.canonical(tag)
        if canonical is None:
            return None, None
        return canonical, (tag if canonical != tag else None)

    def normalize(self, tags) -> List[str]:
        out: List[str] = []
        for t in tags or []:
            c = self.canonical(t)
            if c and c not in out:
                out.append(c)
        return out

    def alias_spec(self) -> Dict[str, str]:
        """Return the normalized raw-alias -> canonical table for glass-box UIs."""
        return dict(sorted(self.aliases.items()))

    def write_json(self, path: str | Path) -> None:
        """Write canonical terms and aliases as editable JSON."""
        by_canonical: Dict[str, List[str]] = {c: [] for c in sorted(self.terms)}
        canonical_keys = {_key(c) for c in self.terms}
        value_keys = {_key(c.split(":", 1)[-1]) for c in self.terms}
        for raw, canonical in sorted(self.aliases.items()):
            if raw in canonical_keys or raw in value_keys:
                continue
            by_canonical.setdefault(canonical, []).append(
                self.alias_surfaces.get(raw, raw)
            )
        Path(path).write_text(
            json.dumps(by_canonical, indent=2, sort_keys=True),
            encoding="utf-8",
        )
