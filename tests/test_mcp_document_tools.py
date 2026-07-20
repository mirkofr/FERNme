"""MCP document tool tests using fictional files and temporary stores."""
from __future__ import annotations

import importlib.util
import json
import sys

import pytest

from fernme.api import mcp_server
from fernme.service import FernService
from fernme.store.sqlite_store import SQLiteStore


requires_fernmark = pytest.mark.skipif(
    importlib.util.find_spec("fernmark") is None,
    reason="fernmark optional extra is not installed",
)


def _service(monkeypatch):
    service = FernService(store=SQLiteStore(":memory:"))
    monkeypatch.setattr(mcp_server, "svc", service)
    return service


def _make_envelope(tmp_path):
    import fernmark

    body = (
        "# Fictional Borealis Brief\n\n"
        "Elena studies Python for a fictional document archive.\n"
    )
    source = tmp_path / "fictional-borealis.txt"
    source.write_text(body, encoding="utf-8")
    document = fernmark.convert(source)
    envelope = tmp_path / "fictional-borealis.fernmark.json"
    fernmark.dump_document(document, envelope)
    return body, document, envelope


@requires_fernmark
def test_confirm_false_is_redacted_preview_with_no_writes_or_consent(
        tmp_path, monkeypatch):
    body, document, envelope = _make_envelope(tmp_path)
    service = _service(monkeypatch)

    report = mcp_server.import_document(
        str(envelope), "demo.com", "elena", confirm=False)

    assert report["ok"] is True
    assert report["dry_run"] is True
    assert report["documents"][0]["source_sha256_prefix"] == (
        document.source_sha256[:12])
    assert "source_sha256" not in report["documents"][0]
    assert service.store.has_consent("demo.com", "elena") is False
    assert service.store.recall("demo.com", "elena", limit=100) == []
    assert body not in json.dumps(report)


@requires_fernmark
def test_confirm_true_imports_idempotently_and_returns_forget_identifier(
        tmp_path, monkeypatch):
    body, document, envelope = _make_envelope(tmp_path)
    service = _service(monkeypatch)

    first = mcp_server.import_document(
        str(envelope), "demo.com", "elena", confirm=True)
    second = mcp_server.import_document(
        str(envelope), "demo.com", "elena", confirm=True)

    assert first["documents_imported"] == 1
    assert first["events_added"] == 1
    assert first["documents"][0]["source_sha256"] == document.source_sha256
    assert second["documents_imported"] == 0
    assert second["events_added"] == 0
    assert second["skipped"]["already_imported"] == 1
    assert service.store.has_consent("demo.com", "elena") is True
    assert len(service.recall("demo.com", "elena", type="document")) == 1
    assert body not in json.dumps(first)


@requires_fernmark
def test_forget_document_returns_service_report_and_removes_event(
        tmp_path, monkeypatch):
    _, document, envelope = _make_envelope(tmp_path)
    service = _service(monkeypatch)
    mcp_server.import_document(
        str(envelope), "demo.com", "elena", confirm=True)

    report = mcp_server.forget_document(
        document.source_sha256, "demo.com", "elena")

    assert report == {
        "forgotten": True,
        "source_sha256": document.source_sha256,
        "events_deleted": 1,
        "suggestions_deleted": 0,
        "attrs_rebuilt": 3,
    }
    assert service.recall("demo.com", "elena", type="document") == []


def test_missing_fernmark_extra_returns_clean_install_error(
        tmp_path, monkeypatch):
    envelope = tmp_path / "placeholder.fernmark.json"
    envelope.write_text("{}", encoding="utf-8")
    _service(monkeypatch)
    monkeypatch.setitem(sys.modules, "fernmark", None)

    report = mcp_server.import_document(
        str(envelope), "demo.com", "elena", confirm=False)

    assert report["ok"] is False
    assert "fernme[fernmark]" in report["error"]
    assert "fernmark==0.4.0a9" in report["error"]
    assert "Traceback" not in json.dumps(report)


@requires_fernmark
def test_invalid_envelope_error_redacts_body_and_local_path(
        tmp_path, monkeypatch):
    fictional_body = "Fictional private body that must not cross MCP."
    envelope = tmp_path / "hostile.fernmark.json"
    envelope.write_text(fictional_body, encoding="utf-8")
    _service(monkeypatch)

    report = mcp_server.import_document(
        str(envelope), "demo.com", "elena", confirm=False)

    encoded = json.dumps(report)
    assert report["error"] == "invalid FERNmark document envelope"
    assert fictional_body not in encoded
    assert str(tmp_path) not in encoded
    assert "Traceback" not in encoded


@pytest.mark.parametrize("hostile_path", [
    "missing/document.fernmark.json",
    "missing/../still-missing.fernmark.json",
    r"\\.\NUL",
])
def test_hostile_or_nonexistent_paths_return_clean_errors(
        hostile_path, monkeypatch):
    _service(monkeypatch)

    report = mcp_server.import_document(
        hostile_path, "demo.com", "elena", confirm=False)

    assert report["ok"] is False
    assert "existing regular file or directory" in report["error"]
    assert "Traceback" not in json.dumps(report)
