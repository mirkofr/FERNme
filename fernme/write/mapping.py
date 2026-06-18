"""Event -> attribute mapping. THE COST CRUX: this is a pure function over
structured event fields + a catalog/taxonomy table. NO LLM call in the hot path.
(Optional offline LLM enrichment of the catalog is a separate batch job and is
deliberately not implemented here, to keep the write path provably LLM-free.)"""
from __future__ import annotations
from typing import Dict, List, Tuple
from ..core.graph import Event


class Catalog:
    """Maps item ids -> attribute tags (the site's existing product/service
    metadata). A join, not an inference."""
    def __init__(self, items: Dict[str, List[str]] | None = None):
        self.items: Dict[str, List[str]] = items or {}

    def attrs_for(self, item_id: str) -> List[str]:
        return self.items.get(item_id, [])


# event types that carry a negative signal -> map to negative attributes
NEGATIVE_TYPES = {"decline", "return", "cancel"}


def map_event(event: Event, catalog: Catalog) -> List[Tuple[str, float]]:
    """Returns [(attr, magnitude)]. Deterministic. magnitude in (0,1]."""
    out: List[Tuple[str, float]] = []
    payload = event.payload
    qty = float(payload.get("qty", 1) or 1)
    # magnitude: qty-weighted, squashed into (0,1]
    mag = min(1.0, 0.5 + 0.5 * (qty / (qty + 2.0)) * 2.0)

    item_id = payload.get("item_id")
    tags = catalog.attrs_for(item_id) if item_id else []
    # also accept tags passed directly on the payload (e.g. category/slot fields)
    tags = list(tags) + list(payload.get("tags", []))

    neg = event.type in NEGATIVE_TYPES
    for t in tags:
        attr = f"!{t}" if neg else t   # negative edges are first-class, prefixed '!'
        out.append((attr, mag))
    return out
