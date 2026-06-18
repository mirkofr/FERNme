"""Proactive triggers — turning memory into a nudge. Two kinds:
  - due_reorders: a cadence numeric (e.g. milk_cadence_days=7) + the last time the
    item was seen => "likely to reorder now".
  - fading_favorites: a once-strong preference that hasn't been reinforced lately
    => "you used to buy X — still want it?".
Pure functions over the graph + cabinet; the service wires them to storage."""
from __future__ import annotations
from typing import Dict, List


CADENCE_SUFFIX = "_cadence_days"


def _last_seen(events, token: str):
    last = None
    for e in events:
        tags = list(e.get("payload", {}).get("tags", [])) + [a for a, _ in e.get("attrs", [])]
        if any(token == t or token == t.split(":", 1)[0] for t in tags):
            last = max(last, e["ts"]) if last is not None else e["ts"]
    return last


def due_reorders(numeric: Dict, events: List[Dict], now: float) -> List[Dict]:
    out = []
    for key, val in numeric.items():
        if not key.endswith(CADENCE_SUFFIX):
            continue
        item = key[: -len(CADENCE_SUFFIX)]
        try:
            cad = float(val)
        except (TypeError, ValueError):
            continue
        last = _last_seen(events, item)
        if last is not None and (now - last) >= cad:
            out.append({"item": item, "cadence_days": cad,
                        "days_since": round(now - last, 1),
                        "overdue_days": round(now - last - cad, 1)})
    return sorted(out, key=lambda d: -d["overdue_days"])


def fading_favorites(ug, now: float, min_hits: int = 4, stale_days: float = 14.0) -> List[Dict]:
    out = []
    for attr, e in ug.edges.items():
        if e.source == "guessed":
            continue
        if e.hits >= min_hits and (now - e.last_reinforced) >= stale_days:
            out.append({"attr": attr, "hits": e.hits,
                        "stale_days": round(now - e.last_reinforced, 1)})
    return sorted(out, key=lambda d: -d["stale_days"])
