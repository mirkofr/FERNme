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
    r"(ignore (all )?(the )?(previous|above|prior)|system:|assistant:|<\|.*?\|>|\{\{|\}\}|"
    r"prompt|disregard|override|http[s]?://|new instructions|you are now|"
    r"exfiltrat|</?\s*(memory|system|instructions?)\b)", re.I)


def looks_like_injection(text: str) -> bool:
    """True if ``text`` reads like an instruction aimed at the agent. Word
    separators common in tags (``_``, ``-``, ``.``) count as spaces, so
    ``ignore_all_previous_instructions`` is caught like the spaced version."""
    return bool(_INJECTION.search(text) or
                _INJECTION.search(re.sub(r"[_\-.]+", " ", text)))


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
        if looks_like_injection(raw):             # drop instruction-like content
            continue
        clean = _ALLOWED.sub("", raw.lower())     # keep only token chars
        if clean and clean not in seen:
            seen.add(clean); out.append(clean)
        if len(out) >= MAX_TAGS:
            break
    return out


def sanitize_display_text(value, limit: int = 180) -> str:
    """Normalize untrusted display-only text without treating it as a tag.

    Display strings may retain punctuation and Unicode, but control characters
    are replaced, whitespace is collapsed, and length is bounded. Callers must
    still store or render the result as data, never as code, SQL, or a path.
    """
    text = re.sub(r"[\x00-\x1f\x7f]", " ", str(value)).strip()
    return " ".join(text.split())[:max(0, int(limit))]


def sanitize_glosses(glosses, limit: int = 160) -> dict:
    """Agent-supplied ``{tag: meaning}`` notes: keys must be valid tags, values
    are bounded display text, and instruction-like values are dropped."""
    if not isinstance(glosses, dict):
        return {}
    out = {}
    for tag, meaning in list(glosses.items())[:MAX_TAGS]:
        clean = sanitize_tags([tag]) if isinstance(tag, str) else []
        if not clean or not isinstance(meaning, str):
            continue
        text = sanitize_display_text(meaning, limit)
        if text and not looks_like_injection(text):
            out[clean[0]] = text
    return out


def cap_numeric(value, lo: float = -1e6, hi: float = 1e6):
    """Clamp numeric values; pass through short strings (e.g. size 'M')."""
    try:
        v = float(value)
        return max(lo, min(v, hi))
    except (TypeError, ValueError):
        s = str(value)[:32]
        return s
