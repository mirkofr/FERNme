"""MCP document tool tests using fictional files and temporary stores."""
from __future__ import annotations

import importlib.util
import json
from dataclasses import replace
from pathlib import Path
import sys

import pytest

from fernme.api import mcp_server
from fernme.config import DEFAULT
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


def _managed_service(tmp_path, monkeypatch):
    service = FernService(
        store=SQLiteStore(str(tmp_path / "managed-mcp.db")),
        cfg=replace(DEFAULT, managed_documents_enabled=True),
        vault_root=str(tmp_path / "vault"),
    )
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


def test_mcp_environment_enables_managed_documents_and_vault(
        tmp_path, monkeypatch):
    vault = tmp_path / "configured-vault"
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("FERNME_MANAGED_DOCUMENTS", "true")
    monkeypatch.setenv("FERNME_VAULT", str(vault))

    service = mcp_server._configured_service(str(tmp_path / "configured.db"))

    assert service.cfg.managed_documents_enabled is True
    assert service.vault_root == vault.resolve()


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
    "bad\x00name.fernmark.json",
])
def test_hostile_or_nonexistent_paths_return_clean_errors(
        hostile_path, monkeypatch):
    _service(monkeypatch)

    report = mcp_server.import_document(
        hostile_path, "demo.com", "elena", confirm=False)

    assert report["ok"] is False
    assert "existing regular file or directory" in report["error"]
    assert "Traceback" not in json.dumps(report)


@requires_fernmark
def test_managed_raw_document_mcp_preview_confirm_recall_and_forget(
        tmp_path, monkeypatch):
    body = "# Fictional MCP raw source\n\nSynthetic document evidence.\n"
    source = tmp_path / "fictional-source.txt"
    source.write_text(body, encoding="utf-8")
    service = _managed_service(tmp_path, monkeypatch)

    preview = mcp_server.import_document(
        str(source), "demo.com", "elena", confirm=False)

    preview_item = preview["documents"][0]
    assert preview["ok"] is True and preview["dry_run"] is True
    assert len(preview_item["source_sha256_prefix"]) == 12
    assert "source_sha256" not in preview_item
    assert preview_item["planned_markdown_path"].startswith("documents/")
    assert service.store.has_consent("demo.com", "elena") is False
    assert not (tmp_path / "vault").exists()
    assert body not in json.dumps(preview)

    confirmed = mcp_server.import_document(
        str(source), "demo.com", "elena", confirm=True)
    item = confirmed["documents"][0]
    assert item["document_id"]
    assert len(item["source_sha256"]) == 64
    assert item["markdown_path"].startswith("documents/")
    assert str(tmp_path) not in json.dumps(confirmed)

    proposal = service.propose_tags(
        "demo.com", "elena", ["topic:synthetic"],
        document_id=item["document_id"], ts=2.0)
    service.accept_suggestion(
        "demo.com", "elena", proposal["suggestion"]["suggestion_id"], ts=3.0)
    recalled = mcp_server.recall_documents(
        ["topic:synthetic"], 5, False, None, "demo.com", "elena")
    assert recalled["documents"][0]["document_id"] == item["document_id"]
    assert body not in json.dumps(recalled)

    page = mcp_server.read_document(item["document_id"], 0, 10, "demo.com", "elena")
    assert page["returned_chars"] == 10
    assert page["has_more"] is True
    assert body not in json.dumps(page)  # only the requested 10-char slice

    use = mcp_server.remember_document_use(
        item["document_id"], "drafted a summary", ["topic:synthetic"],
        None, None, "demo.com", "elena", 4.0)
    assert use["document_id"] == item["document_id"]
    assert "doc:" + item["source_sha256"][:12] in use["stored_attrs"]

    forgotten = mcp_server.forget_document(
        item["document_id"], "demo.com", "elena", True)
    assert forgotten["files_deleted"] == 2
    assert Path(source).exists()


@requires_fernmark
def test_mcp_document_writes_default_to_current_time(tmp_path, monkeypatch):
    current = 1_725_000_000.0
    monkeypatch.setattr("fernme.service._time.time", lambda: current)
    source = tmp_path / "fictional-current-time.txt"
    source.write_text(
        "# Fictional current-time document\n\nSynthetic evidence only.\n",
        encoding="utf-8",
    )
    service = _managed_service(tmp_path, monkeypatch)

    confirmed = mcp_server.import_document(
        str(source), "demo.com", "elena", confirm=True)
    item = confirmed["documents"][0]
    row = service.store.get_document(
        "demo.com", "elena", item["document_id"])
    event = service.store.recall(
        "demo.com", "elena", type="document", limit=1)[0]

    assert row["created_ts"] == current
    assert row["imported_ts"] == current
    assert event["ts"] == current

    proposal = mcp_server.propose_tags(
        ["topic:synthetic"], document_id=item["document_id"],
        source_sha256=item["source_sha256"], site="demo.com", user="elena")

    assert proposal["suggestion"]["created_ts"] == current


@requires_fernmark
def test_backfill_documents_mcp_tool_previews_then_confirms(tmp_path, monkeypatch):
    _, document, envelope = _make_envelope(tmp_path)
    service = _managed_service(tmp_path, monkeypatch)
    legacy_report = service.import_fernmark(
        "demo.com", "elena", str(envelope), dry_run=False, now=1.0)
    assert legacy_report["tags_written"] == 3
    assert service.store.list_documents("demo.com", "elena") == []

    preview = mcp_server.backfill_documents(False, "demo.com", "elena")
    assert preview == {
        "dry_run": True, "site": "demo.com", "user": "elena",
        "candidates_found": 1, "documents_created": 0,
    }

    confirmed = mcp_server.backfill_documents(True, "demo.com", "elena")
    assert confirmed["documents_created"] == 1
    rows = service.store.list_documents("demo.com", "elena")
    assert rows[0]["source_sha256"] == document.source_sha256
