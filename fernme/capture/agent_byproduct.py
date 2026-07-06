"""agent — low-cost capture by piggybacking on the host agent's own reply.

The realistic FERNme path when you are *already* talking to an LLM agent
(Claude Cowork, Codex, ...). The agent appends a tiny tag line as a byproduct of
the answer it is generating anyway — there is NO separate model call. The only
cost is the handful of extra output tokens of the tag line itself (~20-40).

This adapter does not call any model. It just parses the marker line the agent
emitted out of the event text and hands the tags to the 0-LLM write path.

Convention (either works):
    FERN_TAGS: pref:concise topic:python goal:launch
    <!--FERN pref:concise topic:python-->
"""
from __future__ import annotations
import re
from typing import Dict, List

from .base import BaseAdapter
from ..safety import sanitize_tags

_LINE = re.compile(r"FERN_TAGS:\s*(.+)", re.IGNORECASE)
_HTML = re.compile(r"<!--\s*FERN\s+(.+?)-->", re.IGNORECASE | re.DOTALL)


class AgentByproductAdapter(BaseAdapter):
    name = "agent"
    cost_label = "~20-40 tokens/write — emitted inside a reply already happening (no separate call)"
    cost_tokens = 30
    reads_text = True
    needs = "a host agent that appends a 'FERN_TAGS:' line"

    def __init__(self, marker: str = "FERN_TAGS:"):
        self.marker = marker

    def extract(self, event: Dict) -> List[str]:
        # explicit tags passed by the agent win outright
        tags: List[str] = list(event.get("tags", []))
        text = event.get("text") or ""
        m = _LINE.search(text) or _HTML.search(text)
        if m:
            tags += [t for t in re.split(r"[\s,]+", m.group(1).strip()) if ":" in t]
        return sanitize_tags(tags)
