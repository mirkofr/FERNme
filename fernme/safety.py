"""Untrusted-input safety. Event payloads come from the open web, so tags are
treated as DATA, never instructions. We allowlist characters, cap size/count, and
drop anything that looks like an injected instruction before it can become a
memory attribute. (Defense-in-depth; the agent layer must still separate channels.)"""
from __future__ import annotations
import re
from typing import List

MAX_TAG_LEN = 64
MAX_TAGS = 32
_ALLOWED = re.compile(r"[^a-z0-9_:!\-]")          # attributes are simple tokens
_INJECTION = re.compile(
    r"(ignore (the )?(previous|above)|system:|assistant:|<\|.*?\|>|\{\{|\}\}|"
    r"prompt|disregard|override|http[s]?://)", re.I)


def sanitize_tags(tags) -> List[str]:
    out, seen = [], set()
    if not isinstance(tags, (list, tuple)):
        return []
    for t in tags:
        if not isinstance(t, str):
            continue
        raw = t.strip()
        if not raw or len(raw) > MAX_TAG_LEN:
            continue
        if _INJECTION.search(raw):                # drop instruction-like content
            continue
        clean = _ALLOWED.sub("", raw.lower())     # keep only token chars
        if clean and clean not in seen:
            seen.add(clean); out.append(clean)
        if len(out) >= MAX_TAGS:
            break
    return out


def cap_numeric(value, lo: float = -1e6, hi: float = 1e6):
    """Clamp numeric values; pass through short strings (e.g. size 'M')."""
    try:
        v = float(value)
        return max(lo, min(v, hi))
    except (TypeError, ValueError):
        s = str(value)[:32]
        return s
