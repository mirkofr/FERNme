"""Runtime defaults shared by CLI, MCP, REST, and service entry points."""
from __future__ import annotations

import os
from dataclasses import replace

from .config import DEFAULT, Config


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


def configured_features(config_path: str = "fern.toml") -> Config:
    """Resolve default-off adapter feature flags for local entry points."""
    from .capture.config import load_config

    settings = load_config(config_path)
    media = settings.get("media", {})
    documents = settings.get("documents", {})
    document_enabled = _as_bool(documents.get("enabled", False))
    env_document_enabled = os.environ.get("FERNME_MANAGED_DOCUMENTS")
    if env_document_enabled is not None:
        document_enabled = _as_bool(env_document_enabled)
    return replace(
        DEFAULT,
        media_enabled=_as_bool(media.get("enabled", False)),
        media_max_bytes=int(media.get("max_bytes", DEFAULT.media_max_bytes)),
        media_thumbnail_max_px=int(media.get(
            "thumbnail_max_px", DEFAULT.media_thumbnail_max_px)),
        managed_documents_enabled=document_enabled,
        document_overlay_limit=int(documents.get(
            "overlay_limit", DEFAULT.document_overlay_limit)),
    )


def _as_bool(value: object) -> bool:
    return value is True or str(value).strip().lower() in (
        "1", "true", "yes", "on")
