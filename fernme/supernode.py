"""Supernode — the USER-OWNED cross-site profile.

Lego model: a person creates one FERN account (person_id). When they SIGN IN
with it on a site, that site's micro-memory is *linked* (not silently matched).
build_supernode() snaps the linked bricks into one merged graph. The person owns
it; each site only ever sees view_for_site(), a scoped slice they're permitted.

Two hard rules keep this on the right side of the privacy line:
  1. Linking happens by user sign-in (consent), never by behind-the-back matching.
  2. Sensitive bricks (health/allergy, dating, finance...) are walled off by
     default and only crossed with explicit per-site permission.
"""
from __future__ import annotations
from typing import Dict, List
from .core.graph import UserGraph
from .config import Config, DEFAULT

# attribute name tokens treated as special-category by default -> not shared cross-site
SENSITIVE_TOKENS = ("allergy", "health", "medical", "condition", "dating", "match",
                    "sexual", "orientation", "religion", "politic", "income",
                    "wealth", "salary", "loneliness", "mental")


def is_sensitive(attr: str) -> bool:
    a = attr.lstrip("!").lower()
    base = a.split(":", 1)[0]
    return any(tok in a or tok == base for tok in SENSITIVE_TOKENS)


def category_of(attr: str) -> str:
    """Coarse category for share policy (prefix before ':' or the attr itself)."""
    return attr.lstrip("!").split(":", 1)[0]


class Supernode:
    """A merged view with provenance. Owned by the person, assembled on demand."""
    def __init__(self, person: str):
        self.person = person
        # attr -> {"weight": int, "confidence": float, "sources": {site: weight}, "sensitive": bool}
        self.attrs: Dict[str, Dict] = {}
        self.numeric: Dict[str, Dict] = {}   # key -> {"value": v, "sources": [site]}

    def add_from_site(self, site: str, ug: UserGraph, exclude_attrs=None):
        excluded = set(exclude_attrs or ())
        for attr, e in ug.edges.items():
            if attr in excluded:
                continue
            slot = self.attrs.setdefault(attr, {"weight": 0.0, "confidence": 0.0,
                                                "sources": {}, "sensitive": is_sensitive(attr)})
            slot["sources"][site] = e.wire_weight()
            slot["weight"] = max(slot["weight"], e.weight)        # strongest evidence anywhere
            slot["confidence"] = max(slot["confidence"], e.confidence)
        for k, v in ug.numeric.items():
            slot = self.numeric.setdefault(k, {"value": v, "sources": []})
            if site not in slot["sources"]:
                slot["sources"].append(site)
            slot["value"] = v

    # ---- owner's full view (the person sees everything, with provenance) ----
    def owner_card(self, cfg: Config = DEFAULT) -> Dict:
        links = []
        for attr, slot in sorted(self.attrs.items(), key=lambda kv: -kv[1]["weight"]):
            links.append({"attr": attr, "w": int(round(slot["weight"])),
                          "known": slot["confidence"] >= cfg.conf_known,
                          "sensitive": slot["sensitive"],
                          "from": sorted(slot["sources"].keys())})
        return {"person": self.person, "links": links,
                "numeric": {k: v["value"] for k, v in self.numeric.items()}}

    # ---- scoped view a single site is allowed to see ----
    def view_for_site(self, target_site: str, shares: Dict[str, bool],
                      cfg: Config = DEFAULT) -> Dict:
        """DEFAULT-DENY for cross-site. A site sees (a) the bricks it contributed
        itself, plus (b) any category the user EXPLICITLY shares with it. With no
        policy, a site learns nothing it didn't already collect — no silent
        cross-site profiling. A site never sees which other sites contributed."""
        out = []
        for attr, slot in sorted(self.attrs.items(), key=lambda kv: -kv[1]["weight"]):
            cat = category_of(attr)
            own = target_site in slot["sources"]
            allowed = shares.get(cat) is True
            if not (own or allowed):
                continue
            out.append({"attr": attr, "w": int(round(slot["weight"])),
                        "known": slot["confidence"] >= cfg.conf_known,
                        "via": "own" if own else "shared"})
        wire = f"person:{self.person}@{target_site} | " + \
               " ".join(f"{l['attr']}:{l['w']}{'*' if l['known'] else '?'}" for l in out)
        return {"target_site": target_site, "links": out, "wire": wire}
