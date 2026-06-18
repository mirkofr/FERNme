"""Synthetic commerce environment: a tagged catalog + user personas with latent
preferences + an event stream. Lets us prove cost flatness and run ablations
WITHOUT a live site. (A real site is only needed for the outcome-lift claim.)"""
from __future__ import annotations
import random
from typing import Dict, List, Tuple
from ..core.graph import Event

ATTRS = ["organic", "price_sensitive", "bulk", "vegan", "gluten_free",
         "premium", "local", "snacks", "beverages", "household",
         "cheese", "bread", "produce", "dairy", "frozen"]
SIZES = ["size:S", "size:M", "size:L"]


def make_catalog(n_items: int = 200, seed: int = 0) -> Dict[str, List[str]]:
    rng = random.Random(seed)
    cat = {}
    for i in range(n_items):
        tags = rng.sample(ATTRS, k=rng.randint(2, 4))
        if rng.random() < 0.4:
            tags.append(rng.choice(SIZES))
        cat[f"item{i}"] = tags
    return cat


def make_personas(n: int = 50, seed: int = 1, shared: float = 0.0) -> List[Dict]:
    """Each persona has a latent preference vector over ATTRS (0..1). `shared`
    mixes in a population-level base preference (base + individual deviation),
    modelling real populations that share structure; 0.0 = i.i.d. users."""
    rng = random.Random(seed)
    base = {a: (rng.random() ** 2) for a in ATTRS}
    personas = []
    for u in range(n):
        ind = {a: (rng.random() ** 2) for a in ATTRS}
        prefs = {a: shared * base[a] + (1.0 - shared) * ind[a] for a in ATTRS}
        size = rng.choice(SIZES)
        personas.append({"user": f"u{u}", "prefs": prefs, "size": size})
    return personas


def _pick_item(persona, catalog, rng) -> str:
    """Persona is more likely to buy items matching its latent prefs."""
    best, best_score = None, -1.0
    for _ in range(8):  # sample a few, take the most preference-aligned
        item = rng.choice(list(catalog.keys()))
        tags = catalog[item]
        score = sum(persona["prefs"].get(t, 0.0) for t in tags)
        score += 0.5 if persona["size"] in tags else 0.0
        score += rng.random() * 0.3
        if score > best_score:
            best, best_score = item, score
    return best


def stream_events(persona, catalog, n_events: int, site="s1", seed: int = 0) -> List[Event]:
    rng = random.Random(seed)
    events = []
    for d in range(n_events):
        item = _pick_item(persona, catalog, rng)
        etype = "purchase"
        # occasional decline of a non-preferred upsell -> negative signal
        if rng.random() < 0.12:
            etype = "decline"
            item = rng.choice(list(catalog.keys()))
        events.append(Event(site, persona["user"], float(d), etype,
                            {"item_id": item, "qty": rng.randint(1, 3)}))
    return events
