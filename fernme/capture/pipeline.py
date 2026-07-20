"""CapturePipeline — run the active adapters over an event, then write once.

This is the only object an integration needs: hand it an event, it asks each
active adapter for tags, merges them, and calls the normal 0-LLM
`service.observe`. It also reports the rough billed-token cost of the write so a
caller can be transparent about it.
"""
from __future__ import annotations
from typing import Dict, List

from .base import BaseAdapter
from .extractors import extract_structured


class CapturePipeline:
    def __init__(self, svc, site: str, user: str, adapters: List[BaseAdapter]):
        self.svc = svc
        self.site = site
        self.user = user
        self.adapters = adapters

    def ingest(self, event: Dict, ts: float = 0.0) -> Dict:
        """Run adapters -> merge tags -> observe(). Returns stored attrs +
        which adapters contributed + the rough billed-token cost."""
        text = event.get("text")
        structured = extract_structured(text or "")
        adapter_event = dict(event)
        if structured:
            adapter_event["structured"] = structured
        tags: List[str] = []
        used: List[str] = []
        payload_fields = set()
        for ad in self.adapters:
            got = ad.extract(adapter_event)
            if got:
                tags.extend(got)
                used.append(ad.name)
                payload_fields.update(ad.payload_fields)
        tags = sorted(set(tags))
        payload: Dict = {"tags": tags}
        if text:
            payload["text"] = text
        if structured:
            payload["structured"] = structured
        for key in sorted(payload_fields):
            if key in adapter_event:
                payload[key] = adapter_event[key]
        res = self.svc.observe(self.site, self.user, event.get("kind", "chat"),
                               payload, ts=ts)
        res["adapters_fired"] = used
        res["billed_tokens"] = sum(a.cost_tokens for a in self.adapters
                                   if a.name in used)
        return res

    def cost_summary(self) -> List[Dict]:
        return [a.info() for a in self.adapters]
