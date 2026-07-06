"""Minimal JSON persistence for FERN state (v0). Lets memory survive across
processes/sessions, which is what makes a real 'does it remember?' test honest:
we write in one process and read back in a fresh one."""
from __future__ import annotations
import json, os
from typing import Tuple
from ..core.graph import UserGraph, AssocGraph, Edge
from ..prior.population import PopulationPrior


def _edge_to_dict(e: Edge) -> dict:
    return {"weight": e.weight, "confidence": e.confidence, "source": e.source,
            "last_reinforced": e.last_reinforced, "hits": e.hits, "fast": e.fast}


def save_state(path: str, ug: UserGraph, assoc: AssocGraph,
               prior: PopulationPrior | None = None,
               suggestions: list[dict] | None = None) -> None:
    data = {
        "user_graph": {
            "site": ug.site, "user": ug.user,
            "edges": {a: _edge_to_dict(e) for a, e in ug.edges.items()},
            "numeric": ug.numeric,
            "history": ug.history,
        },
        "assoc": {"site": assoc.site,
                  "edges": {f"{k[0]}|{k[1]}": v for k, v in assoc.edges.items()}},
    }
    if prior is not None:
        data["prior"] = {"site": prior.site, "_sum": prior._sum,
                         "_n": prior._n, "n_users": prior.n_users}
    if suggestions is not None:
        data["canonicalization_suggestions"] = suggestions
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, path)


def load_state(path: str) -> Tuple[UserGraph, AssocGraph, PopulationPrior | None]:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    ugd = data["user_graph"]
    ug = UserGraph(ugd["site"], ugd["user"])
    ug.numeric = ugd.get("numeric", {})
    ug.history = {k: list(v) for k, v in ugd.get("history", {}).items()}
    for a, ed in ugd["edges"].items():
        ug.edges[a] = Edge(**ed)
    ad = data["assoc"]
    assoc = AssocGraph(ad["site"])
    for k, v in ad["edges"].items():
        x, y = k.split("|", 1)
        assoc.edges[(x, y)] = v
    prior = None
    if "prior" in data:
        pd = data["prior"]
        prior = PopulationPrior(pd["site"])
        prior._sum = pd["_sum"]; prior._n = pd["_n"]; prior.n_users = pd["n_users"]
    return ug, assoc, prior


def load_suggestions(path: str) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return list(data.get("canonicalization_suggestions", []))
