"""Identity namespaces shared by write and service layers."""

IDENTITY_NS = {
    "name", "role", "employer", "company", "affiliation", "position", "origin",
    "city", "birthday", "nationality", "lang", "domain",
}


def namespace(attr: str) -> str:
    base = attr.lstrip("!")
    return base.split(":", 1)[0] if ":" in base else base


def is_identity_attr(attr: str) -> bool:
    return namespace(attr) in IDENTITY_NS
