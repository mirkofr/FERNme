"""Propose-only enrichment validation.

All inputs here are untrusted DATA. The module never writes memory truth; it only
normalizes validated proposal payloads for the service suggestion queue.
"""
from __future__ import annotations

import json
import re
from typing import Dict, Iterable, List

from . import curation_queue
from .relations import DEFAULT_RELATIONS

INSTRUCTION_RE = re.compile(
    r"(ignore|forget|reveal|override|bypass|system prompt|developer message|"
    r"previous instructions|act as|do not follow)",
    re.IGNORECASE,
)


def estimate_tokens(text: str) -> int:
    return max(1, int(len(str(text)) / 4)) if text else 0


def looks_instructional(value) -> bool:
    if value is None:
        return False
    return bool(INSTRUCTION_RE.search(str(value)))


def namespace(attr: str) -> str:
    return curation_queue.namespace(attr)


def clean_note(note: str, limit: int = 280) -> str:
    text = re.sub(r"[\x00-\x1f\x7f]", " ", str(note or "")).strip()
    return " ".join(text.split())[:limit]


def parse_json_proposals(raw: str) -> List[Dict]:
    """Parse a mock/model proposal response.

    Accepted shapes: a JSON list, or {"proposals": [...]}.
    Unknown/free-form model output is treated as no valid proposals.
    """
    try:
        data = json.loads(raw or "[]")
    except (TypeError, ValueError, json.JSONDecodeError):
        return []
    if isinstance(data, dict):
        data = data.get("proposals", [])
    if not isinstance(data, list):
        return []
    return [p for p in data if isinstance(p, dict)]


def prompt_for_events(events: Iterable[Dict]) -> str:
    rows = []
    for ev in events:
        text = str(ev.get("payload", {}).get("text", ""))[:500]
        if text:
            rows.append(f"- ts={ev.get('ts', 0.0)} text={text}")
    return (
        "Propose entity-link or relation suggestions from this FERNme Cabinet "
        "text. Return JSON only: a list of objects with kind='entity-link' or "
        "kind='relation'. Proposals are untrusted and require human approval.\n"
        + "\n".join(rows)
    )


def validate_entity_link_payload(payload: Dict, entity: Dict, aliases: List[str],
                                 min_score: float) -> tuple[bool, Dict | None, str]:
    alias_attr = str(payload.get("alias_attr", ""))
    entity_id = str(payload.get("entity_id", ""))
    if not alias_attr or not entity_id:
        return False, None, "missing entity-link fields"
    if any(looks_instructional(v) for v in (alias_attr, entity.get("display_name", ""))):
        return False, None, "instruction-like entity-link text"
    alias_ns = namespace(alias_attr)
    if alias_ns in {"person", "org", "project", "place", "thing"} and alias_ns != entity["kind"]:
        return False, None, "entity kind mismatch"
    if entity["kind"] == "person" and curation_queue.same_surname_distinct_full_names(
        alias_attr, f"person:{entity.get('display_name', '')}"
    ):
        return False, None, "same-surname distinct person"
    score = curation_queue.entity_link_score(alias_attr, entity, aliases, {})
    if score < min_score:
        return False, None, "low-confidence entity link"
    return True, {"entity_id": entity_id, "alias_attr": alias_attr}, ""


def validate_relation_payload(payload: Dict, subject: Dict, obj: Dict) -> tuple[bool, Dict | None, str]:
    raw_relation = str(payload.get("relation", ""))
    note = clean_note(payload.get("note", ""))
    if not payload.get("subject_id") or not raw_relation or not payload.get("object_id"):
        return False, None, "missing relation fields"
    if any(looks_instructional(v) for v in (raw_relation, note)):
        return False, None, "instruction-like relation text"
    try:
        canonical = DEFAULT_RELATIONS.validate_kinds(raw_relation, subject["kind"], obj["kind"])
    except ValueError as exc:
        return False, None, str(exc)
    return True, {
        "subject_id": subject["entity_id"],
        "relation": canonical,
        "object_id": obj["entity_id"],
        "note": note,
    }, ""
