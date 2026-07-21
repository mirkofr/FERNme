"""Optional FERNmark schema-v1 document capture adapter.

FERNmark remains the only envelope validation boundary. This module imports it
only inside ``load_envelope`` so every non-document FERNme path works without
the optional dependency installed.
"""
from __future__ import annotations

import os
import re
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


def _fernmark():
    try:
        import fernmark
    except ImportError as exc:
        raise FernmarkDocumentError(
            "FERNmark document support requires the fernme[fernmark] optional "
            "extra (fernmark==0.4.0a9 from immutable commit 23e16ea5b01f)"
        ) from exc
    return fernmark


def load_envelope(source, max_bytes: int = DEFAULT_MAX_BYTES):
    """Load one untrusted envelope through FERNmark's validated schema API."""
    fernmark = _fernmark()

    try:
        if isinstance(source, (bytes, bytearray)) or (
                isinstance(source, str) and source.lstrip().startswith("{")):
            return fernmark.loads_document(source, max_bytes=max_bytes)
        return fernmark.load_document(source, max_bytes=max_bytes)
    except (fernmark.FernmarkError, OSError, TypeError, ValueError) as exc:
        raise FernmarkDocumentError(f"invalid FERNmark document envelope: {exc}") from exc


def load_source(source, max_bytes: int = DEFAULT_MAX_BYTES):
    """Convert a raw local document or load an existing canonical envelope."""
    path = os.path.abspath(os.fspath(source))
    if path.lower().endswith(".fernmark.json"):
        return load_envelope(path, max_bytes=max_bytes)
    if not os.path.isfile(path):
        raise FernmarkDocumentError("document source must be a regular file")
    fernmark = _fernmark()
    try:
        return fernmark.convert(path, max_file_bytes=max_bytes)
    except (fernmark.FernmarkError, OSError, TypeError, ValueError) as exc:
        raise FernmarkDocumentError(f"invalid or unsupported document source: {exc}") from exc


def canonical_envelope(document, max_bytes: int = DEFAULT_MAX_BYTES) -> str:
    """Serialize a validated document through FERNmark's canonical API."""
    fernmark = _fernmark()
    try:
        return fernmark.dumps_document(document, max_bytes=max_bytes)
    except (fernmark.FernmarkError, OSError, TypeError, ValueError) as exc:
        raise FernmarkDocumentError(f"could not serialize FERNmark document: {exc}") from exc


def _validated_title(document) -> str:
    """First FERNmark ``title``-kind block, as bounded display text.

    This is validated structured metadata (FERNmark classified the block as a
    title), not a free read of arbitrary body text, so it is safe to sanitize
    and expose as a short tag slug alongside the other identity metadata.
    """
    for block in document.blocks:
        if getattr(block, "kind", None) != "title":
            continue
        text = re.sub(r"^#{1,6}\s+", "", block.markdown or "").strip()
        if text:
            return sanitize_display_text(text, 80)
    return ""


def document_event(document, *, managed: bool = False,
                   from_envelope: bool = False) -> Dict:
    """Map a validated FernmarkDocument to deterministic capture data.

    ``managed`` and ``from_envelope`` are additive, additional identity facts
    known at capture time (whether this event belongs to the managed vault
    catalog workflow, and whether the source was already a FERNmark envelope
    rather than a raw converted file). Both are present for preview and
    confirm alike so a dry-run report matches what confirm will propose.
    """
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
        "managed": bool(managed),
        "from_envelope": bool(from_envelope),
        "title": _validated_title(document),
    }


class DocumentAdapter(BaseAdapter):
    """Propose document identity tags from validated structured metadata.

    This is the original Phase 15 tag set (unchanged for backwards
    compatibility with ``import_fernmark``): document identity, MIME, and
    extraction quality only.
    """

    name = "document"
    cost_label = "0 tokens -- deterministic tags from validated FERNmark metadata"
    cost_tokens = 0
    reads_text = False
    needs = "fernmark==0.4.0a9 to load schema-v1 envelopes"
    payload_fields = _PROVENANCE_FIELDS

    def extract(self, event: Dict) -> List[str]:
        if event.get("kind") != IMPORT_EVENT_TYPE:
            return []
        return sanitize_tags(self._raw_tags(event))

    def _raw_tags(self, event: Dict) -> List[str]:
        sha256 = str(event.get("source_sha256") or "")
        mime_type = str(event.get("mime_type") or "")
        quality = str(event.get("extraction_quality") or "")
        raw = [f"doc:{sha256[:12]}"] if sha256 else []
        if "/" in mime_type:
            raw.append(f"mime:{mime_type.split('/', 1)[1]}")
        if quality:
            raw.append(f"quality:{quality}")
        return raw


_MANAGED_PAYLOAD_FIELDS = _PROVENANCE_FIELDS + (
    "managed", "from_envelope", "title", "document_id",
    "markdown_path", "envelope_path", "catalog_status",
)


class ManagedDocumentAdapter(DocumentAdapter):
    """Level-1 tags for the managed vault catalog workflow (default-off).

    Extends the base identity tags with more deterministic, zero-LLM facts
    that only make sense once a document is durably cataloged: how the source
    arrived (raw file vs an existing envelope), that it is now a vault-managed
    artifact, its catalog lifecycle status at import time, a safe title when
    FERNmark classified one, and any explicit task/use tags the calling
    workflow already knows about (e.g. from ``remember_document_use``). No new
    tagging engine and no model calls: every tag here is read straight off
    already-validated structured fields and run through the same tag
    sanitizer as the base adapter.
    """

    name = "managed_document"
    cost_label = ("0 tokens -- deterministic tags from validated FERNmark "
                  "metadata plus managed-catalog identity")
    payload_fields = _MANAGED_PAYLOAD_FIELDS

    def extract(self, event: Dict) -> List[str]:
        if event.get("kind") != IMPORT_EVENT_TYPE:
            return []
        raw = list(self._raw_tags(event))
        if event.get("managed"):
            raw.append("origin:envelope" if event.get("from_envelope")
                       else "origin:raw")
            raw.append("vault:managed")
            status = str(event.get("catalog_status") or "active")
            raw.append(f"docstatus:{status}")
        title = str(event.get("title") or "")
        if title:
            slug = re.sub(r"\s+", "-", title.lower()).strip("-")
            if slug:
                raw.append(f"title:{slug}"[:64])
        raw.extend(str(tag) for tag in (event.get("task_tags") or []))
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
    "ManagedDocumentAdapter",
    "canonical_envelope",
    "document_event",
    "envelope_paths",
    "load_envelope",
    "load_source",
]
