"""Optional FERNmark schema-v1 document capture adapter.

FERNmark remains the only envelope validation boundary. This module imports it
only inside ``load_envelope`` so every non-document FERNme path works without
the optional dependency installed.
"""
from __future__ import annotations

import os
from typing import Dict, List

from .base import BaseAdapter
from ..safety import sanitize_display_text, sanitize_tags


DEFAULT_MAX_BYTES = 64 * 1024 * 1024
IMPORT_EVENT_TYPE = "document"
IMPORTER_NAME = "fernmark"
_PROVENANCE_FIELDS = (
    "source_sha256",
    "source_name",
    "mime_type",
    "extraction_quality",
    "warning_count",
    "extractor",
    "block_count",
    "importer",
)


class FernmarkDocumentError(ValueError):
    """A FERNmark dependency or envelope failure normalized for FERNme."""


def load_envelope(source, max_bytes: int = DEFAULT_MAX_BYTES):
    """Load one untrusted envelope through FERNmark's validated schema API."""
    try:
        import fernmark
    except ImportError as exc:
        raise FernmarkDocumentError(
            "FERNmark document support requires the fernme[fernmark] optional "
            "extra (fernmark==0.4.0a9)"
        ) from exc

    try:
        if isinstance(source, (bytes, bytearray)) or (
                isinstance(source, str) and source.lstrip().startswith("{")):
            return fernmark.loads_document(source, max_bytes=max_bytes)
        return fernmark.load_document(source, max_bytes=max_bytes)
    except (fernmark.FernmarkError, OSError, TypeError, ValueError) as exc:
        raise FernmarkDocumentError(f"invalid FERNmark document envelope: {exc}") from exc


def document_event(document) -> Dict:
    """Map a validated FernmarkDocument to deterministic capture data."""
    return {
        "kind": IMPORT_EVENT_TYPE,
        "text": document.markdown,
        "source_sha256": document.source_sha256,
        "source_name": sanitize_display_text(document.source_name, 180),
        "mime_type": document.mime_type,
        "extraction_quality": document.extraction_quality,
        "warning_count": len(document.warnings),
        "extractor": document.extractor,
        "block_count": len(document.blocks),
        "importer": IMPORTER_NAME,
    }


class DocumentAdapter(BaseAdapter):
    """Propose document identity tags from validated structured metadata."""

    name = "document"
    cost_label = "0 tokens -- deterministic tags from validated FERNmark metadata"
    cost_tokens = 0
    reads_text = False
    needs = "fernmark==0.4.0a9 to load schema-v1 envelopes"
    payload_fields = _PROVENANCE_FIELDS

    def extract(self, event: Dict) -> List[str]:
        if event.get("kind") != IMPORT_EVENT_TYPE:
            return []
        sha256 = str(event.get("source_sha256") or "")
        mime_type = str(event.get("mime_type") or "")
        quality = str(event.get("extraction_quality") or "")
        raw = [f"doc:{sha256[:12]}"] if sha256 else []
        if "/" in mime_type:
            raw.append(f"mime:{mime_type.split('/', 1)[1]}")
        if quality:
            raw.append(f"quality:{quality}")
        return sanitize_tags(raw)


def envelope_paths(source) -> List[str]:
    """Resolve a file or a flat directory of ``*.fernmark.json`` envelopes."""
    path = os.path.abspath(os.fspath(source))
    if os.path.isfile(path):
        return [path]
    if os.path.isdir(path):
        return sorted(
            os.path.join(path, name)
            for name in os.listdir(path)
            if name.endswith(".fernmark.json") and os.path.isfile(os.path.join(path, name))
        )
    raise FernmarkDocumentError("envelope source must be a file or directory")


__all__ = [
    "DEFAULT_MAX_BYTES",
    "DocumentAdapter",
    "FernmarkDocumentError",
    "document_event",
    "envelope_paths",
    "load_envelope",
]
