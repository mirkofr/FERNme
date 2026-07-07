"""Runtime defaults shared by CLI, MCP, REST, and service entry points."""
from __future__ import annotations

import os


DEFAULT_SITE = "default"
DEFAULT_USER = "local"


def default_db_path() -> str:
    """Resolve the canonical SQLite path without creating the database."""
    override = os.environ.get("FERNME_DB")
    if override:
        return os.path.abspath(os.path.expanduser(override))
    return os.path.join(os.path.expanduser("~"), ".fernme", "fernme.db")


def ensure_default_db_path(path: str | None = None) -> str:
    """Resolve the DB path and create the parent directory if needed."""
    if path == ":memory:":
        return path
    resolved = os.path.abspath(os.path.expanduser(path or default_db_path()))
    parent = os.path.dirname(resolved)
    if parent:
        os.makedirs(parent, exist_ok=True)
    return resolved


def default_site() -> str:
    return os.environ.get("FERNME_SITE") or DEFAULT_SITE


def default_user() -> str:
    return os.environ.get("FERNME_USER") or DEFAULT_USER
