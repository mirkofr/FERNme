"""Baselines for the recall-quality comparison. Each receives the SAME catalog
access FERN has, so tags are resolved from item_id identically (fair comparison).

frequency / recency are LLM-free and run anywhere. A real Mem0 (LLM-extraction)
baseline is the honest head-to-head but needs an API key + the mem0 package; we
provide the hook and skip cleanly if absent so CI stays deterministic."""
from __future__ import annotations
from collections import Counter
from typing import List


def _tags(ev, catalog) -> List[str]:
    item = ev.payload.get("item_id")
    tags = list(catalog.attrs_for(item)) if item else []
    return tags + list(ev.payload.get("tags", []))


def frequency_topk(events, catalog, k: int) -> List[str]:
    c = Counter()
    for e in events:
        for t in _tags(e, catalog):
            c[t] += 1
    return [a for a, _ in c.most_common(k)]


def recency_topk(events, catalog, k: int) -> List[str]:
    seen = {}
    for i, e in enumerate(events):
        for t in _tags(e, catalog):
            seen[t] = i
    return [a for a, _ in sorted(seen.items(), key=lambda kv: -kv[1])[:k]]


def mem0_topk_if_available(events, catalog, k: int):
    """Real LLM-extraction baseline. Returns (None, reason) unless mem0 + an API
    key are present. Run locally with keys to fill the head-to-head cell."""
    import os
    if not os.environ.get("OPENAI_API_KEY"):
        return None, "skipped: set OPENAI_API_KEY and `pip install mem0ai` to run"
    try:
        from mem0 import Memory
    except Exception:
        return None, "skipped: mem0ai not installed"
    m = Memory(); uid = "eval_user"
    for e in events:
        m.add(f"bought item with tags {_tags(e, catalog)}", user_id=uid)
    res = m.search("what does this user prefer?", user_id=uid, limit=k)
    return [r.get("memory", "") for r in res.get("results", [])], "ok"
