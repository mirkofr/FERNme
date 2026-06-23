"""Per-memory meaning, deterministic and LLM-free.

A bare tag like `topic:salience` is ambiguous. This adds two cheap layers:

  CONTEXT  the sentence a memory came from. It is just the event `text`, already
           stored on write, so surfacing it costs nothing. Free.
  GLOSS    a short 'what it means'. Supplied by whoever tags (the host agent as a
           byproduct of its reply, or a local model) when available; otherwise a
           deterministic namespace template, so even the zero-token path produces
           something. No LLM is ever called here.

The service assembles a user's glossary from stored events (latest gloss wins,
context is the most recent sentence the tag appeared in).
"""
from __future__ import annotations
from typing import Dict, List, Optional

# namespace -> generic one-line meaning (the 0-token fallback)
NAMESPACE_GLOSS = {
    "pref": "a stated preference",
    "rel": "a person in their network",
    "goal": "a goal or intention",
    "topic": "a topic of interest",
    "project": "a project",
    "company": "a company or organization",
    "role": "a role someone holds",
    "trait": "a personal trait",
    "style": "a communication style",
    "habit": "a habit or routine",
    "tool": "a tool or service used",
    "feature": "a product feature",
    "design": "a design decision",
    "milestone": "a milestone reached",
    "context": "background context",
    "entity": "a named entity",
    "field": "a field of work",
    "name": "their name",
    "nickname": "a nickname",
    "email": "an email address",
    "github": "a GitHub handle",
    "domain": "a web domain",
    "city": "a city",
    "diet": "a dietary choice",
    "likes": "something they like",
    "food": "a food",
    "activity": "an activity",
    "status": "a status or state",
}
DEFAULT_GLOSS = "a remembered detail"


def namespace_of(attr: str) -> str:
    base = attr.lstrip("!")
    return base.split(":", 1)[0] if ":" in base else "attr"


def gloss_for(attr: str, custom: Optional[str] = None) -> str:
    """A custom gloss wins; otherwise a deterministic namespace template. No LLM."""
    if custom:
        return custom
    base = NAMESPACE_GLOSS.get(namespace_of(attr), DEFAULT_GLOSS)
    return ("a dislike: " + base) if attr.startswith("!") else base


def assemble(events: List[Dict], auto: bool = True) -> Dict[str, Dict]:
    """Build {attr: {gloss, context, ts}} from stored events, latest wins.

    Reads each event's payload['glosses'] (attr -> gloss) and payload['text']
    (the context sentence). With auto=True, any tag still missing a gloss gets a
    namespace template so nothing renders blank."""
    out: Dict[str, Dict] = {}
    for e in sorted(events, key=lambda ev: ev.get("ts", 0)):
        p = e.get("payload", {}) or {}
        text = p.get("text", "")
        glosses = p.get("glosses", {}) or {}
        for tag in p.get("tags", []):
            cur = out.get(tag, {})
            supplied = glosses.get(tag)
            out[tag] = {
                "gloss": supplied or cur.get("gloss") or (gloss_for(tag) if auto else ""),
                "context": text or cur.get("context", ""),
                "ts": e.get("ts", 0),
            }
    return out
