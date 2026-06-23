"""The editing policy — deterministic conflict detection + resolution. No LLM.

This is the "librarian" layer the engine was missing: when a new memory arrives,
decide whether it *supersedes* an old one, *coexists* with it, or is a *tension*
that should be raised with the user instead of silently resolved. Four pieces,
matching the known gaps:

  1. Conflict detection beyond polarity:
       - polarity      likes:x   vs  !likes:x
       - same-slot     diet:vegetarian -> diet:pescatarian  (single-value slots)
       - semantic      diet:vegetarian  vs  likes:steak     (declared mutex)
  2. Authority axis: an *inferred* signal can never silently override an
     *explicit* statement. Explicit + recent wins; inferred-vs-explicit escalates.
  3. Supersession is recorded (the caller tombstones via the event log), never a
     silent delete -- the raw record stays honest.
  4. When it's a real tension, we emit a 0-token clarifying QUESTION for the agent
     to actually ask, instead of guessing.

Everything here is pure: it reads attribute strings + light edge metadata and
returns decisions. The service applies them (and writes the tombstone event).
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, Iterable, List, Mapping

# Namespaces that hold exactly ONE value: a new value replaces the old.
SINGLE_VALUE_SLOTS = {
    "diet", "name", "city", "status", "role", "employer", "birthday", "origin",
    "field", "timezone", "tier", "plan", "pronoun", "company",
}

# Mutually-exclusive CHOICE groups (cross-slot, same concept): pick exactly one.
EXCLUSIVE_GROUPS = [
    {"pref:dark-mode", "pref:light-mode"},
    {"status:single", "status:married", "status:divorced", "status:partnered"},
]

# Declared semantic oppositions: any attr on the left clashes with any on the
# right. This is the small controlled-vocabulary "knowledge" that pure namespace
# matching cannot infer. Extend freely; the rare unlisted case escalates anyway.
OPPOSE = [
    ({"diet:vegetarian", "diet:vegan"},
     {"likes:steak", "likes:meat", "likes:bacon", "food:meat", "food:beef",
      "food:pork", "food:chicken"}),
    ({"diet:vegan"},
     {"likes:dairy", "likes:cheese", "likes:milk", "food:dairy", "food:eggs"}),
]

# Authority: explicit user statement outranks behavioral inference.
_AUTH = {"override": 3, "stated": 2, "known": 2, "inferred": 1, "guessed": 1}
ASK_DEFAULT_THRESHOLD = 0.4   # only escalate a tension if importance >= this


def authority(source: str) -> int:
    return _AUTH.get(source, 2)


def _build_conflict_map() -> Dict[str, set]:
    m: Dict[str, set] = {}

    def add(a: str, b: str) -> None:
        m.setdefault(a, set()).add(b)
        m.setdefault(b, set()).add(a)

    for group in EXCLUSIVE_GROUPS:
        members = list(group)
        for i in range(len(members)):
            for j in range(i + 1, len(members)):
                add(members[i], members[j])
    for left, right in OPPOSE:
        for a in left:
            for b in right:
                add(a, b)
    return m


CONFLICT_MAP = _build_conflict_map()


def namespace(attr: str) -> str:
    base = attr.lstrip("!")
    return base.split(":", 1)[0] if ":" in base else "attr"


def value(attr: str) -> str:
    base = attr.lstrip("!")
    return base.split(":", 1)[1] if ":" in base else ""


def label(attr: str) -> str:
    """Human phrase for a tag, for use in a clarifying question."""
    neg = "not " if attr.startswith("!") else ""
    return neg + attr.lstrip("!").replace(":", " ").replace("-", " ")


@dataclass
class Resolution:
    new_attr: str
    old_attr: str
    kind: str        # polarity | same-slot | semantic
    action: str      # supersede | ask | hold
    question: str = ""   # 0-token template, filled only when action == ask


def detect(new_attr: str, existing: Iterable[str]) -> List[tuple]:
    """Return [(old_attr, kind), ...] conflicts between new_attr and existing."""
    out = []
    base = new_attr.lstrip("!")
    neg = new_attr.startswith("!")
    ns, val = namespace(new_attr), value(new_attr)
    opp = CONFLICT_MAP.get(new_attr, set()) | CONFLICT_MAP.get(base, set())
    for old in existing:
        if old == new_attr:
            continue
        old_base = old.lstrip("!")
        # 1) polarity: same base, opposite sign
        if old_base == base and old.startswith("!") != neg:
            out.append((old, "polarity"))
            continue
        # 2) same single-value slot, different value (both positive)
        if (not neg and not old.startswith("!") and ns in SINGLE_VALUE_SLOTS
                and namespace(old) == ns and value(old) != val):
            out.append((old, "same-slot"))
            continue
        # 3) declared semantic opposition
        if old in opp or old_base in opp:
            out.append((old, "semantic"))
    return out


def resolve(new_source: str, new_ts: float, old_source: str, old_ts: float) -> str:
    """Decide the action for one conflict. The trust-critical rule lives here:
    inferred can NEVER silently override explicit -> it escalates (ask)."""
    na, oa = authority(new_source), authority(old_source)
    if na > oa:
        return "supersede"     # explicit beats inferred: take the new one
    if na < oa:
        return "ask"           # inferred vs explicit: never silent; escalate
    return "supersede" if new_ts >= old_ts else "hold"   # equal: newer wins


def question_for(new_attr: str, old_attr: str) -> str:
    return (f"I have '{label(old_attr)}' on record, but now I'm seeing "
            f"'{label(new_attr)}'. Which is right?")


def review(new_attr: str, new_source: str, new_ts: float,
           existing: Mapping[str, object], importance: float = 0.5,
           ask_threshold: float = ASK_DEFAULT_THRESHOLD) -> List[Resolution]:
    """Full pass for one incoming attribute against the user's current edges.

    `existing` maps attr -> an edge-like object exposing `.source` and
    `.last_reinforced` (anything with those attributes works). Returns one
    Resolution per detected conflict. A tension only becomes `ask` when it is
    important enough; otherwise it's held (the old explicit value just stands)."""
    out: List[Resolution] = []
    for old, kind in detect(new_attr, existing.keys()):
        oe = existing[old]
        action = resolve(new_source, new_ts,
                         getattr(oe, "source", "known"),
                         getattr(oe, "last_reinforced", 0.0))
        if action == "ask" and importance < ask_threshold:
            action = "hold"
        q = question_for(new_attr, old) if action == "ask" else ""
        out.append(Resolution(new_attr, old, kind, action, q))
    return out
