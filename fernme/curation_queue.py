"""Deterministic propose-only canonicalization suggestions.

This module never mutates memory truth. It scores alias-merge and entity-link
candidates from stored graph/entity state so the service can put them in a
human-reviewed queue.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Dict, Iterable, List, Mapping, Sequence, Tuple
from .entity_kinds import canonical_entity_kind

LOW_CONFIDENCE = 0.40


@dataclass(frozen=True)
class SuggestionCandidate:
    kind: str
    payload: Dict
    score: float

    def suggestion_id(self, site: str, user: str) -> str:
        raw = json.dumps(
            {
                "site": site,
                "user": user,
                "kind": self.kind,
                "payload": self.payload,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def row(self, site: str, user: str, created_ts: float) -> Dict:
        return {
            "suggestion_id": self.suggestion_id(site, user),
            "site": site,
            "user": user,
            "kind": self.kind,
            "payload": dict(self.payload),
            "score": round(float(self.score), 6),
            "status": "pending",
            "created_ts": float(created_ts),
            "decided_ts": None,
        }


def namespace(attr: str) -> str:
    base = str(attr).lstrip("!")
    return base.split(":", 1)[0] if ":" in base else "attr"


def value(attr: str) -> str:
    base = str(attr).lstrip("!")
    return base.split(":", 1)[1] if ":" in base else base


def normalize_value(text: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", str(text).lower()))


def tokens(text: str) -> Tuple[str, ...]:
    return tuple(t for t in normalize_value(text).split() if t)


def _display_name(attr: str) -> str:
    return " ".join(t.capitalize() for t in tokens(value(attr)))


def _levenshtein(a: str, b: str) -> int:
    if a == b:
        return 0
    if len(a) < len(b):
        a, b = b, a
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(
                prev[j] + 1,
                cur[j - 1] + 1,
                prev[j - 1] + (0 if ca == cb else 1),
            ))
        prev = cur
    return prev[-1]


def edit_similarity(a: str, b: str) -> float:
    an = normalize_value(a).replace(" ", "")
    bn = normalize_value(b).replace(" ", "")
    if not an or not bn:
        return 0.0
    return 1.0 - (_levenshtein(an, bn) / float(max(len(an), len(bn))))


def token_overlap(a: str, b: str) -> float:
    at, bt = set(tokens(a)), set(tokens(b))
    if not at or not bt:
        return 0.0
    return len(at & bt) / float(len(at | bt))


def same_surname_distinct_full_names(a: str, b: str) -> bool:
    if namespace(a) != "person" or namespace(b) != "person":
        return False
    at, bt = tokens(value(a)), tokens(value(b))
    if len(at) < 2 or len(bt) < 2:
        return False
    return at[-1] == bt[-1] and at[0] != bt[0]


def _person_surface(surface: str) -> str:
    return surface if namespace(surface) == "person" else f"person:{surface}"


def _kind_for_attr(attr: str) -> str:
    return canonical_entity_kind(namespace(attr))


def alias_score(a: str, b: str, assoc_weight: float = 0.0) -> float:
    if namespace(a) != namespace(b):
        return 0.0
    av = value(a)
    bv = value(b)
    if normalize_value(av) == normalize_value(bv):
        score = 0.99
    else:
        score = 0.45 * edit_similarity(av, bv) + 0.45 * token_overlap(av, bv)
        if assoc_weight > 0:
            score += min(0.10, float(assoc_weight) / 90.0)
    if same_surname_distinct_full_names(a, b):
        score = min(score, LOW_CONFIDENCE - 0.01)
    return round(max(0.0, min(0.99, score)), 6)


def entity_link_score(alias_attr: str, entity: Mapping, aliases: Sequence[str],
                      assoc_weights: Mapping[Tuple[str, str], float]) -> float:
    ns = namespace(alias_attr)
    if ns != entity.get("kind"):
        return 0.0
    surfaces = [str(entity.get("display_name", "")), *aliases]
    score = max(
        max(edit_similarity(value(alias_attr), surface),
            token_overlap(value(alias_attr), surface))
        for surface in surfaces
    )
    cooc = max((assoc_weights.get(tuple(sorted((alias_attr, a))), 0.0)
                for a in aliases), default=0.0)
    if cooc > 0:
        score += min(0.10, float(cooc) / 90.0)
    if entity.get("kind") == "person" and any(
        same_surname_distinct_full_names(alias_attr, _person_surface(surface))
        for surface in surfaces
    ):
        score = min(score, LOW_CONFIDENCE - 0.01)
    return round(max(0.0, min(0.99, score)), 6)


def _ordered_pair(a: str, b: str, weights: Mapping[str, float]) -> Tuple[str, str]:
    return sorted((a, b), key=lambda x: (-float(weights.get(x, 0.0)), len(x), x))


def generate_candidates(
    attrs: Iterable[str],
    weights: Mapping[str, float] | None = None,
    assoc_weights: Mapping[Tuple[str, str], float] | None = None,
    entities: Sequence[Mapping] = (),
    aliases_by_entity: Mapping[str, Sequence[str]] | None = None,
    min_score: float = 0.55,
) -> List[SuggestionCandidate]:
    weights = weights or {}
    assoc_weights = assoc_weights or {}
    aliases_by_entity = aliases_by_entity or {}
    attr_list = sorted(set(str(a) for a in attrs))
    linked_aliases = {a for aliases in aliases_by_entity.values() for a in aliases}
    out: List[SuggestionCandidate] = []

    for i, a in enumerate(attr_list):
        for b in attr_list[i + 1:]:
            if a in linked_aliases and b in linked_aliases:
                continue
            key = tuple(sorted((a, b)))
            score = alias_score(a, b, assoc_weights.get(key, 0.0))
            if score < min_score:
                continue
            canonical, alias = _ordered_pair(a, b, weights)
            out.append(SuggestionCandidate(
                "alias-merge",
                {
                    "canonical_attr": canonical,
                    "alias_attr": alias,
                    "entity_kind": _kind_for_attr(canonical),
                    "display_name": _display_name(canonical),
                },
                score,
            ))

    for attr in attr_list:
        if attr in linked_aliases:
            continue
        for entity in sorted(entities, key=lambda e: (e.get("display_name", ""), e.get("entity_id", ""))):
            entity_id = entity["entity_id"]
            aliases = tuple(sorted(aliases_by_entity.get(entity_id, ())))
            score = entity_link_score(attr, entity, aliases, assoc_weights)
            if score >= min_score:
                out.append(SuggestionCandidate(
                    "entity-link",
                    {"entity_id": entity_id, "alias_attr": attr},
                    score,
                ))

    dedup: Dict[Tuple[str, str], SuggestionCandidate] = {}
    for cand in out:
        key = (
            cand.kind,
            json.dumps(cand.payload, sort_keys=True, separators=(",", ":")),
        )
        prev = dedup.get(key)
        if prev is None or cand.score > prev.score:
            dedup[key] = cand
    return sorted(dedup.values(), key=lambda c: (
        -c.score,
        c.kind,
        json.dumps(c.payload, sort_keys=True, separators=(",", ":")),
    ))
