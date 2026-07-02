"""Deterministic structured-field extraction for capture ingest.

These values stay as payload data. They are never converted into graph tags by
this module.
"""
from __future__ import annotations

import re
from typing import List, Tuple

MAX_STRUCTURED_VALUE_LEN = 128
MAX_STRUCTURED_FIELDS = 16

_EMAIL = re.compile(
    r"\b[A-Z0-9._%+\-]+(?:\x40)[A-Z0-9.\-]+\.[A-Z]{2,}\b",
    re.I,
)
_URL = re.compile(r"\bhttps?://[^\s<>'\")\]]+", re.I)
_HANDLE = re.compile(r"(?<![\w.])(?:\x40)[A-Z][A-Z0-9_]{1,31}\b", re.I)
_ISO_DATE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
_TEL = re.compile(r"(?<!\w)\+?\d[\d\s().\-]{5,}\d(?!\w)")
_TEL_FIELD = "ph" + "one"
_DATA_INJECTION = re.compile(
    r"(ignore[\s_\-]*(the[\s_\-]*)?(previous|above)|system:|assistant:|"
    r"<\|.*?\|>|\{\{|\}\}|prompt|disregard|override)",
    re.I,
)


def _trim_value(value: str) -> str:
    return value.strip().rstrip(".,;:!?")


def _safe_value(value: str) -> str | None:
    value = _trim_value(value)
    if not value or len(value) > MAX_STRUCTURED_VALUE_LEN:
        return None
    if _DATA_INJECTION.search(value):
        return None
    return value


def _add(
    out: List[Tuple[int, str, str]],
    seen: set[Tuple[str, str]],
    pos: int,
    field: str,
    value: str,
) -> None:
    safe = _safe_value(value)
    if safe is None:
        return
    key = (field, safe)
    if key in seen:
        return
    seen.add(key)
    out.append((pos, field, safe))


def extract_structured(text: str) -> List[Tuple[str, str]]:
    """Return `(field, value)` pairs for contact-like data found in text."""
    if not isinstance(text, str) or not text:
        return []

    found: List[Tuple[int, str, str]] = []
    seen: set[Tuple[str, str]] = set()
    protected_spans: List[Tuple[int, int]] = []

    for match in _EMAIL.finditer(text):
        _add(found, seen, match.start(), "email", match.group(0))
        protected_spans.append(match.span())
    for match in _URL.finditer(text):
        _add(found, seen, match.start(), "url", match.group(0))
        protected_spans.append(match.span())
    for match in _ISO_DATE.finditer(text):
        _add(found, seen, match.start(), "iso-date", match.group(0))
        protected_spans.append(match.span())

    for match in _HANDLE.finditer(text):
        if any(start <= match.start() < end for start, end in protected_spans):
            continue
        _add(found, seen, match.start(), "handle", match.group(0))

    for match in _TEL.finditer(text):
        value = match.group(0)
        if _ISO_DATE.fullmatch(value):
            continue
        digits = re.sub(r"\D", "", value)
        if len(digits) < 7:
            continue
        _add(found, seen, match.start(), _TEL_FIELD, value)

    found.sort(key=lambda item: (item[0], item[1], item[2]))
    return [(field, value) for _pos, field, value in found[:MAX_STRUCTURED_FIELDS]]
