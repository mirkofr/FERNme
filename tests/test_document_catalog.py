"""Durable managed-document tests with fictional files and temporary vaults."""
from __future__ import annotations

from dataclasses import replace
import importlib.util
import json
from pathlib import Path

import pytest

from fernme import documents as document_files
from fernme.capture.fernmark_documents import load_envelope
from fernme.config import DEFAULT
from fernme.service import ConsentError, FernService
from fernme.store.sqlite_store import SQLiteStore


pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("fernmark") is None,
    reason="fernmark optional extra is not installed",
)


def _service(tmp_path, *, enabled=True):
    return FernService(
        store=SQLiteStore(str(tmp_path / "fictional-memory.db")),
        cfg=replace(DEFAULT, managed_documents_enabled=enabled),
        vault_root=str(tmp_path / "fictional-vault"),
    )


def _source(tmp_path, name="fictional-brief.txt", body=None):
    path = tmp_path / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body or (
        "# Fictional Borealis Brief\n\n"
        "Synthetic archive evidence about Python and observatories.\n"
    ), encoding="utf-8")
    return path


def _confirm(service, source, *, site="demo.com", user="elena", now=2.0):
    return service.import_document(
        site, user, str(source), dry_run=False, now=now)


def _targets(service, item):
    return (
        Path(service.vault_root) / item["markdown_path"],
        Path(service.vault_root) / item["envelope_path"],
    )


def test_confirmed_import_writes_native_tags_through_the_real_graph(tmp_path):
    """Regression for the Phase 18 defect: the managed import path once wrote
    events with attrs=[] and reported tags_written=0, so native document tags
    (doc:/mime:/quality:) never reached the graph. This must fail against the
    pre-fix code, where ``service.graph(...)`` would contain no such nodes and
    ``tags_written`` would be 0."""
    service = _service(tmp_path)
    item = _confirm(service, _source(tmp_path))["documents"][0]

    report = service.store.recall("demo.com", "elena", type="document")[0]
    assert report["attrs"], "confirmed import must map real graph attrs"

    g = service.graph("demo.com", "elena", assoc_floor=0.0, hierarchy=False)
    node_ids = {node["id"] for node in g["nodes"]}
    assert "doc:" + item["source_sha256"][:12] in node_ids
    assert "mime:plain" in node_ids
    assert "quality:good" in node_ids
    edge_pairs = {(edge["source"], edge["target"]) for edge in g["edges"]}
    assert ("user:elena", "doc:" + item["source_sha256"][:12]) in edge_pairs
    assert ("user:elena", "mime:plain") in edge_pairs
    assert ("user:elena", "quality:good") in edge_pairs


def test_managed_document_engine_flag_is_default_off(tmp_path):
    service = _service(tmp_path, enabled=False)
    source = _source(tmp_path)

    with pytest.raises(ValueError, match="managed document workflow is disabled"):
        service.import_document(
            "demo.com", "elena", str(source), dry_run=True, now=1.0)

    assert not Path(service.vault_root).exists()


def test_vault_defaults_to_file_backed_database_directory(tmp_path, monkeypatch):
    monkeypatch.delenv("FERNME_VAULT", raising=False)
    service = FernService(
        db_path=str(tmp_path / "fictional-memory.db"),
        cfg=replace(DEFAULT, managed_documents_enabled=True),
    )

    assert service.vault_root == tmp_path.resolve()


def test_raw_preview_is_redacted_and_performs_zero_persistent_writes(tmp_path):
    service = _service(tmp_path)
    source = _source(tmp_path)

    report = service.import_document(
        "demo.com", "elena", str(source), dry_run=True, now=1.0)

    item = report["documents"][0]
    assert item["document_id"] is None
    assert item["source_sha256_prefix"] and "source_sha256" not in item
    assert item["mime_type"] == "text/plain"
    assert item["markdown_path"].startswith("documents/")
    assert item["envelope_path"].startswith("documents/")
    assert report["events_added"] == 0
    assert report["tags_written"] == 0
    assert service.store.has_consent("demo.com", "elena") is False
    assert service.store.list_documents("demo.com", "elena") == []
    assert service.store.list_suggestions("demo.com", "elena") == []
    assert service.store.recall("demo.com", "elena", limit=100) == []
    assert not Path(service.vault_root).exists()
    assert "Synthetic archive evidence" not in json.dumps(report)


def test_confirm_writes_utf8_envelope_catalog_and_cabinet_idempotently(tmp_path):
    service = _service(tmp_path)
    source = _source(tmp_path)

    first = _confirm(service, source)
    second = _confirm(service, source, now=3.0)

    item = first["documents"][0]
    markdown, envelope = _targets(service, item)
    assert markdown.read_text(encoding="utf-8").startswith("# Fictional")
    loaded = load_envelope(envelope)
    assert loaded.source_sha256 == item["source_sha256"]
    assert not Path(item["markdown_path"]).is_absolute()
    assert not Path(item["envelope_path"]).is_absolute()
    record = service.store.get_document(
        "demo.com", "elena", item["document_id"])
    assert record["authoritative"] is False
    assert record["markdown_path"] == item["markdown_path"]
    events = service.store.recall("demo.com", "elena", type="document")
    assert len(events) == 1
    assert "Synthetic archive evidence" in events[0]["payload"]["text"]
    # Native Level-1 tags must reach the graph through the real write path
    # (CapturePipeline -> DocumentAdapter -> service.observe), not attrs=[].
    stored_attrs = {attr for attr, _weight in events[0]["attrs"]}
    assert stored_attrs == {
        "doc:" + item["source_sha256"][:12],
        "mime:plain", "quality:good", "origin:raw", "vault:managed",
        "docstatus:active",
    }
    assert first["tags_written"] == len(stored_attrs)
    assert second["events_added"] == 0
    assert second["skipped"]["already_imported"] == 1
    assert len(list(markdown.parent.iterdir())) == 2


def test_existing_envelope_confirmation_also_creates_markdown(tmp_path):
    import fernmark

    source = _source(tmp_path)
    document = fernmark.convert(source)
    supplied = tmp_path / "supplied.fernmark.json"
    fernmark.dump_document(document, supplied)
    service = _service(tmp_path)

    report = _confirm(service, supplied)

    markdown, envelope = _targets(service, report["documents"][0])
    assert markdown.read_text(encoding="utf-8") == document.markdown
    assert load_envelope(envelope) == document
    assert supplied.exists()


def test_partial_extraction_and_warnings_are_reported_honestly(tmp_path):
    import fernmark

    source = _source(tmp_path)
    document = replace(
        fernmark.convert(source), extraction_quality="partial",
        warnings=("fictional extraction warning",))
    envelope = tmp_path / "partial.fernmark.json"
    fernmark.dump_document(document, envelope)
    service = _service(tmp_path)

    report = service.import_document(
        "demo.com", "elena", str(envelope), dry_run=True)

    assert report["warnings"] == 1
    assert report["quality"]["partial"] == 1
    assert report["documents"][0]["warning_count"] == 1
    assert report["documents"][0]["quality"] == "partial"
    assert "fictional extraction warning" not in json.dumps(report)


def test_collisions_and_hostile_names_are_deterministic_and_vault_safe(tmp_path):
    service = _service(tmp_path)
    first_source = _source(
        tmp_path / "one", "shared.txt", "Fictional first document.\n")
    second_source = _source(
        tmp_path / "two", "shared.md", "Fictional second document.\n")
    hostile = _source(
        tmp_path / "three", ".. hostile ; DROP TABLE.txt",
        "Fictional hostile-name document.\n")

    first = _confirm(service, first_source, now=1.0)["documents"][0]
    second = _confirm(service, second_source, now=2.0)["documents"][0]
    third = _confirm(service, hostile, now=3.0)["documents"][0]

    assert first["markdown_path"].endswith("/shared.md")
    assert second["markdown_path"].endswith(
        "--" + second["source_sha256"][:12] + ".md")
    assert ".." not in Path(third["markdown_path"]).name
    root = Path(service.vault_root).resolve()
    for item in (first, second, third):
        for target in _targets(service, item):
            assert target.resolve().is_relative_to(root)


def test_file_and_database_failures_leave_no_partial_managed_import(
        tmp_path, monkeypatch):
    service = _service(tmp_path)
    source = _source(tmp_path)
    real_write = document_files._atomic_write_text
    calls = {"count": 0}

    def fail_second_write(path, text):
        calls["count"] += 1
        if calls["count"] == 2:
            raise document_files.DocumentStorageError("fictional write failure")
        return real_write(path, text)

    monkeypatch.setattr(document_files, "_atomic_write_text", fail_second_write)
    with pytest.raises(document_files.DocumentStorageError):
        _confirm(service, source)
    assert service.store.has_consent("demo.com", "elena") is False
    assert service.store.list_documents("demo.com", "elena") == []
    assert not list((Path(service.vault_root) / "documents").rglob("*.*"))

    monkeypatch.setattr(document_files, "_atomic_write_text", real_write)
    monkeypatch.setattr(
        service.store, "insert_document",
        lambda _row: (_ for _ in ()).throw(RuntimeError("fictional DB failure")))
    with pytest.raises(RuntimeError, match="fictional DB failure"):
        _confirm(service, source)
    assert service.store.has_consent("demo.com", "elena") is False
    assert service.store.recall("demo.com", "elena", limit=100) == []
    assert not list((Path(service.vault_root) / "documents").rglob("*.*"))


def test_document_tag_review_provenance_survives_decay_and_is_tenant_safe(tmp_path):
    service = _service(tmp_path)
    item = _confirm(service, _source(tmp_path))["documents"][0]

    with pytest.raises((ConsentError, ValueError)):
        service.propose_tags(
            "other.example", "elena", ["topic:python"],
            document_id=item["document_id"])
    service.consent("other.example", "elena", True)
    with pytest.raises(ValueError, match="active document"):
        service.propose_tags(
            "other.example", "elena", ["topic:python"],
            document_id=item["document_id"])

    proposal = service.propose_tags(
        "demo.com", "elena",
        ["topic:python", "topic:observatory", "topic:fictional"],
        document_id=item["document_id"],
        source_sha256=item["source_sha256"], ts=3.0)
    assert service.store.list_document_tags(
        "demo.com", "elena", item["document_id"]) == []
    service.accept_suggestion(
        "demo.com", "elena", proposal["suggestion"]["suggestion_id"], ts=4.0)

    mappings = service.store.list_document_tags(
        "demo.com", "elena", item["document_id"])
    assert {row["tag"] for row in mappings} == {
        "topic:python", "topic:observatory", "topic:fictional"}
    assert all(row["provenance"] == "human_approved" for row in mappings)
    assoc = service.store.load_assoc("demo.com", user="elena", min_users=1)
    assert assoc.get("topic:python", "topic:observatory") > 0
    service.decay("demo.com", "elena", now=10000.0)
    assert service.store.list_document_tags(
        "demo.com", "elena", item["document_id"]) == mappings


def test_bounded_recall_and_graph_overlay_do_not_change_default_graph(tmp_path):
    service = _service(tmp_path)
    item = _confirm(service, _source(tmp_path))["documents"][0]
    second = _confirm(
        service, _source(
            tmp_path / "second", body="Fictional second Python source.\n"),
        now=2.5)["documents"][0]
    for index, document in enumerate((item, second), start=3):
        tags = (["topic:python", "topic:observatory"]
                if document is item else ["topic:python"])
        proposal = service.propose_tags(
            "demo.com", "elena", tags,
            document_id=document["document_id"], ts=float(index))
        service.accept_suggestion(
            "demo.com", "elena", proposal["suggestion"]["suggestion_id"],
            ts=float(index) + 0.5)

    default_graph = service.graph(
        "demo.com", "elena", assoc_floor=1.0, hierarchy=False)
    explicit_off = service.graph(
        "demo.com", "elena", assoc_floor=1.0, hierarchy=False,
        document_evidence=False)
    assert json.dumps(default_graph, sort_keys=True) == json.dumps(
        explicit_off, sort_keys=True)
    assert "document_overlay" not in default_graph
    assert not any(node["kind"] == "document" for node in default_graph["nodes"])
    # Real document-identity tag co-occurrence (e.g. both fictional documents
    # share mime:plain/quality:good) legitimately produces ordinary Hebbian
    # assoc edges now that native tags reach the graph (Task 1 fix). What must
    # stay false is the overlay leaking document nodes/edges into this
    # unopted-in default view.
    assert not any(edge.get("document_evidence") for edge in default_graph["edges"])
    assert not any(
        str(edge.get("source", "")).startswith("document:") or
        str(edge.get("target", "")).startswith("document:")
        for edge in default_graph["edges"])

    page = service.recall_documents(
        "demo.com", "elena", ["topic:python"], limit=1)
    assert len(page["documents"]) == 1
    assert page["truncated"] is True and page["next_cursor"] == "1"
    continuation = service.recall_documents(
        "demo.com", "elena", ["topic:python"], limit=1,
        cursor=page["next_cursor"])
    assert continuation["documents"][0]["document_id"] != (
        page["documents"][0]["document_id"])
    assert "text" not in page["documents"][0]
    assert "markdown" not in page["documents"][0]
    assert "Synthetic archive evidence" not in json.dumps(page)
    assert not Path(page["documents"][0]["markdown_path"]).is_absolute()
    with pytest.raises(ConsentError):
        service.recall_documents("demo.com", "other-user", limit=5)
    service.consent("demo.com", "other-user", True)
    assert service.recall_documents(
        "demo.com", "other-user", limit=5)["documents"] == []
    overlay = service.graph(
        "demo.com", "elena", assoc_floor=1.0, hierarchy=False,
        document_evidence=True, selected_node="topic:python",
        document_limit=1)
    assert overlay["document_overlay"]["document_count"] == 1
    assert overlay["document_overlay"]["truncated"] is True
    assert {edge["relation"] for edge in overlay["edges"]
            if edge.get("document_evidence")} == {"tagged_with", "supported_by"}
    assert all("text" not in node for node in overlay["nodes"])


def test_archive_supersede_and_explicit_flags_control_retrieval(tmp_path):
    service = _service(tmp_path)
    first = _confirm(
        service, _source(tmp_path / "one", body="Fictional old evidence.\n"),
        now=1.0)["documents"][0]
    second = _confirm(
        service, _source(tmp_path / "two", body="Fictional new evidence.\n"),
        now=2.0)["documents"][0]
    service.set_document_flags(
        "demo.com", "elena", second["document_id"],
        pinned=True, authoritative=True)
    service.supersede_document(
        "demo.com", "elena", first["document_id"], second["document_id"])

    active = service.recall_documents("demo.com", "elena", limit=10)
    assert [row["document_id"] for row in active["documents"]] == [
        second["document_id"]]
    historical = service.recall_documents(
        "demo.com", "elena", limit=10, include_archived=True)
    by_id = {row["document_id"]: row for row in historical["documents"]}
    assert by_id[first["document_id"]]["status"] == "superseded"
    assert by_id[first["document_id"]]["superseded_by"] == second["document_id"]
    assert by_id[second["document_id"]]["pinned"] is True
    assert by_id[second["document_id"]]["authoritative"] is True


def test_forget_preserves_other_evidence_and_deletes_only_managed_files_on_request(
        tmp_path):
    service = _service(tmp_path)
    item = _confirm(service, _source(tmp_path))["documents"][0]
    proposal = service.propose_tags(
        "demo.com", "elena", ["topic:python", "topic:observatory"],
        document_id=item["document_id"], ts=3.0)
    service.accept_suggestion(
        "demo.com", "elena", proposal["suggestion"]["suggestion_id"], ts=4.0)
    service.observe(
        "demo.com", "elena", "chat",
        {"tags": ["topic:python", "topic:observatory"],
         "source": "stated"}, ts=5.0)
    assoc_before = service.store.load_assoc("demo.com").get(
        "topic:python", "topic:observatory")
    original = _source(
        tmp_path / "original", "keep-me.txt", "Fictional original stays.\n")
    managed = _confirm(service, original, now=6.0)["documents"][0]
    managed_targets = _targets(service, managed)

    forgotten = service.forget_document(
        "demo.com", "elena", item["document_id"], ts=7.0)
    assert forgotten["files_deleted"] == 0
    assert "topic:python" in service.store.load_user("demo.com", "elena").edges
    assoc_after = service.store.load_assoc("demo.com").get(
        "topic:python", "topic:observatory")
    assert 0 < assoc_after < assoc_before
    assert service.store.get_document(
        "demo.com", "elena", item["document_id"]) is None

    deleted = service.forget_document(
        "demo.com", "elena", managed["document_id"], ts=8.0,
        delete_managed_files=True)
    assert deleted["files_deleted"] == 2
    assert all(not target.exists() for target in managed_targets)
    assert original.exists()


def test_managed_file_deletion_refuses_traversal(tmp_path):
    vault = tmp_path / "vault"
    outside = tmp_path / "outside.txt"
    outside.write_text("fictional outside data", encoding="utf-8")

    with pytest.raises(document_files.DocumentStorageError):
        document_files.delete_managed_files(
            vault, ["documents/../../outside.txt"])

    assert outside.exists()


def test_sqlite_document_schema_is_additive_and_idempotent(tmp_path):
    path = tmp_path / "old.db"
    first = SQLiteStore(str(path))
    first._conn.close()
    second = SQLiteStore(str(path))

    tables = {row[0] for row in second._conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"documents", "document_tags"} <= tables
    columns = {row[1] for row in second._conn.execute(
        "PRAGMA table_info(documents)")}
    assert {"document_id", "markdown_path", "status", "authoritative"} <= columns


# ---------- Task 2: remember_document_use ----------

def test_remember_document_use_links_task_tag_and_doc_tag_in_one_event(tmp_path):
    service = _service(tmp_path)
    item = _confirm(service, _source(tmp_path))["documents"][0]

    with pytest.raises(ValueError, match="document not found"):
        service.remember_document_use(
            "demo.com", "elena", "not-a-real-id", "drafted a summary")

    result = service.remember_document_use(
        "demo.com", "elena", item["document_id"], "Drafted the client summary!",
        task_tags=["topic:python"], artifact_pointer="documents/out/summary.md",
        use_summary="Used the brief to draft a one-page summary.", ts=5.0)

    assert result["document_id"] == item["document_id"]
    doc_tag = "doc:" + item["source_sha256"][:12]
    assert "task:drafted-the-client-summary" in result["stored_attrs"]
    assert doc_tag in result["stored_attrs"]
    assert "topic:python" in result["stored_attrs"]

    ug = service.store.load_user("demo.com", "elena")
    assert "task:drafted-the-client-summary" in ug.edges
    assoc = service.store.load_assoc("demo.com").get(doc_tag, "task:drafted-the-client-summary")
    assert assoc > 0

    events = service.store.recall("demo.com", "elena", type="document_use")
    assert len(events) == 1
    assert events[0]["payload"]["document_id"] == item["document_id"]
    assert events[0]["payload"]["purpose"] == "Drafted the client summary!"
    assert events[0]["payload"]["artifact_pointer"] == "documents/out/summary.md"


def test_remember_document_use_requires_consent_and_purpose(tmp_path):
    service = _service(tmp_path)
    item = _confirm(service, _source(tmp_path))["documents"][0]

    with pytest.raises(ValueError, match="purpose"):
        service.remember_document_use(
            "demo.com", "elena", item["document_id"], "   ")

    with pytest.raises((ConsentError, ValueError)):
        service.remember_document_use(
            "other.example", "elena", item["document_id"], "reused it")


# ---------- Task 3: read_document ----------

def test_read_document_pages_bounded_content_and_reports_status(tmp_path):
    service = _service(tmp_path)
    item = _confirm(service, _source(tmp_path))["documents"][0]

    with pytest.raises(ValueError, match="max_chars"):
        service.read_document(
            "demo.com", "elena", item["document_id"], max_chars=1_000_000)

    first_page = service.read_document(
        "demo.com", "elena", item["document_id"], offset=0, max_chars=10)
    assert first_page["returned_chars"] == 10
    assert first_page["has_more"] is True
    assert first_page["status"] == "active"
    assert first_page["disabled"] is False
    assert first_page["content_untrusted"] is True

    rest = service.read_document(
        "demo.com", "elena", item["document_id"], offset=10, max_chars=10_000)
    assert first_page["text"] + rest["text"] == "# Fictional Borealis Brief\n\n" \
        "Synthetic archive evidence about Python and observatories.\n"
    assert rest["has_more"] is False

    service.archive_document("demo.com", "elena", item["document_id"])
    archived = service.read_document("demo.com", "elena", item["document_id"])
    assert archived["status"] == "archived"
    assert archived["disabled"] is True
    assert archived["text"]  # still readable, just flagged

    with pytest.raises(ValueError, match="document not found"):
        service.read_document("demo.com", "elena", "not-a-real-id")


def test_read_document_is_audit_logged(tmp_path):
    service = _service(tmp_path)
    item = _confirm(service, _source(tmp_path))["documents"][0]

    service.read_document("demo.com", "elena", item["document_id"], max_chars=5)

    audit = [entry for entry in service.audit_log("demo.com", "elena")
            if entry["action"] == "read_document"]
    assert len(audit) == 1
    assert audit[0]["detail"]["document_id"] == item["document_id"]
    assert audit[0]["detail"]["returned_chars"] == 5


# ---------- Task 4: legacy backfill ----------

def test_backfill_creates_catalog_rows_for_pre_catalog_events_idempotently(
        tmp_path):
    import fernmark

    source = _source(tmp_path)
    document = fernmark.convert(source)
    envelope = tmp_path / "legacy.fernmark.json"
    fernmark.dump_document(document, envelope)

    # Phase 15 style import: no managed catalog involved at all.
    legacy_service = FernService(
        store=SQLiteStore(str(tmp_path / "legacy.db")),
        cfg=replace(DEFAULT, managed_documents_enabled=True),
        vault_root=str(tmp_path / "legacy-vault"))
    legacy_report = legacy_service.import_fernmark(
        "demo.com", "elena", str(envelope), dry_run=False, now=1.0)
    assert legacy_report["tags_written"] == 3
    assert legacy_service.store.list_documents("demo.com", "elena") == []

    dry = legacy_service.backfill_documents(
        "demo.com", "elena", dry_run=True, now=9.0)
    assert dry == {
        "dry_run": True, "site": "demo.com", "user": "elena",
        "candidates_found": 1, "documents_created": 0,
    }
    assert legacy_service.store.list_documents("demo.com", "elena") == []

    confirmed = legacy_service.backfill_documents(
        "demo.com", "elena", dry_run=False, now=9.0)
    assert confirmed["candidates_found"] == 1
    assert confirmed["documents_created"] == 1

    rows = legacy_service.store.list_documents("demo.com", "elena")
    assert len(rows) == 1
    assert rows[0]["markdown_path"] == ""
    assert rows[0]["envelope_path"] == ""
    assert rows[0]["source_sha256"] == document.source_sha256

    # Idempotent: rerunning finds nothing new, and no event was duplicated.
    again = legacy_service.backfill_documents(
        "demo.com", "elena", dry_run=False, now=10.0)
    assert again["candidates_found"] == 0
    assert again["documents_created"] == 0
    assert len(legacy_service.store.recall(
        "demo.com", "elena", type="document")) == 1

    # No graph edges were rewritten by backfilling.
    ug_before_read = legacy_service.store.load_user("demo.com", "elena")
    read = legacy_service.read_document(
        "demo.com", "elena", rows[0]["document_id"])
    assert read["text"] == document.markdown
    assert legacy_service.store.load_user(
        "demo.com", "elena").edges.keys() == ug_before_read.edges.keys()


# ---------- Task 5: empty-state affordance ----------

def test_recall_documents_on_empty_catalog_returns_hint(tmp_path):
    service = _service(tmp_path)
    service.consent("demo.com", "elena", True)

    result = service.recall_documents("demo.com", "elena", limit=5)

    assert result["documents"] == []
    assert "import_document" in result["hint"]

    item = _confirm(service, _source(tmp_path))["documents"][0]
    populated = service.recall_documents("demo.com", "elena", limit=5)
    assert populated["documents"][0]["document_id"] == item["document_id"]
    assert "hint" not in populated


def test_recall_documents_distinguishes_no_match_from_empty_catalog(tmp_path):
    service = _service(tmp_path)
    service.consent("demo.com", "elena", True)
    empty = service.recall_documents(
        "demo.com", "elena", ["topic:missing"], limit=5)
    assert "import_document" in empty["hint"]

    _confirm(service, _source(tmp_path))
    unmatched = service.recall_documents(
        "demo.com", "elena", ["topic:missing"], limit=5)

    assert unmatched["documents"] == []
    assert unmatched["catalog_count"] == 1
    assert "No documents match this query" in unmatched["hint"]
    assert "1 document in the catalog" in unmatched["hint"]
    assert "unapproved tag proposals may be pending" in unmatched["hint"]
    assert "import_document" not in unmatched["hint"]


def test_backfill_does_not_recatalog_already_managed_imports(tmp_path):
    service = _service(tmp_path)
    _confirm(service, _source(tmp_path))

    report = service.backfill_documents(
        "demo.com", "elena", dry_run=True, now=1.0)
    assert report["candidates_found"] == 0
