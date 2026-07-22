import sqlite3

from fernme.core.graph import Event
from fernme.repair_document_timestamps import repair_zero_document_timestamps
from fernme.store.sqlite_store import SQLiteStore


def test_document_timestamp_repair_is_backup_first_and_idempotent(tmp_path):
    db = tmp_path / "fictional-repair.db"
    store = SQLiteStore(str(db))
    document_id = "doc-fictional-repair"
    source_sha256 = "a" * 64
    suggestion_id = "suggestion-fictional-repair"
    store.insert_document({
        "document_id": document_id,
        "site": "demo.com",
        "user": "elena",
        "source_sha256": source_sha256,
        "source_name": "fictional-repair.txt",
        "markdown_path": "vault/fictional-repair.md",
        "envelope_path": "vault/fictional-repair.fernmark.json",
        "mime_type": "text/plain",
        "extraction_quality": "good",
        "warning_count": 0,
        "block_count": 1,
        "created_ts": 0.0,
        "imported_ts": 0.0,
        "status": "active",
    })
    store.append_event(Event(
        "demo.com",
        "elena",
        0.0,
        "document",
        {"document_id": document_id, "source_sha256": source_sha256},
        [("topic:synthetic", 1.0)],
    ))
    store.upsert_suggestion({
        "suggestion_id": suggestion_id,
        "site": "demo.com",
        "user": "elena",
        "kind": "tag_proposal",
        "payload": {
            "document_id": document_id,
            "source_sha256": source_sha256,
            "tags": ["topic:synthetic"],
        },
        "score": 1.0,
        "status": "pending",
        "created_ts": 0.0,
    })
    store._conn.close()

    preview = repair_zero_document_timestamps(db, 1_725_000_000.0)
    assert preview["mode"] == "dry-run"
    assert preview["documents"] == 1
    assert preview["events"] == 1
    assert preview["suggestions"] == 1

    backup = tmp_path / "fictional-repair.backup.db"
    applied = repair_zero_document_timestamps(
        db, 1_725_000_000.0, apply=True, backup_path=backup)
    assert applied["mode"] == "apply"
    assert backup.is_file()

    conn = sqlite3.connect(str(db))
    try:
        assert conn.execute(
            "SELECT created_ts FROM documents WHERE document_id=?",
            (document_id,),
        ).fetchone()[0] == 1_725_000_000.0
        assert conn.execute(
            "SELECT ts FROM events WHERE type='document'"
        ).fetchone()[0] == 1_725_000_000.0
        assert conn.execute(
            "SELECT created_ts FROM canonicalization_suggestions "
            "WHERE suggestion_id=?",
            (suggestion_id,),
        ).fetchone()[0] == 1_725_000_000.0
    finally:
        conn.close()

    repeated = repair_zero_document_timestamps(db, 1_725_000_000.0)
    assert repeated["documents"] == 0
    assert repeated["events"] == 0
    assert repeated["suggestions"] == 0
