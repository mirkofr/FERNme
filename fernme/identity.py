"""Durability namespaces shared by write and service layers."""

PERMANENT_NS = {
    "name", "birthday", "origin", "nationality", "lang", "allergy", "health",
}

SLOW_IDENTITY_NS = {
    "role", "employer", "company", "affiliation", "position", "city", "domain",
}

IDENTITY_NS = PERMANENT_NS | SLOW_IDENTITY_NS


def namespace(attr: str) -> str:
    base = attr.lstrip("!")
    return base.split(":", 1)[0] if ":" in base else base


def is_identity_attr(attr: str) -> bool:
    return namespace(attr) in IDENTITY_NS


def is_permanent_attr(attr: str) -> bool:
    return namespace(attr) in PERMANENT_NS
