import sqlite3

from dataclasses import replace

from fernme.config import DEFAULT
from fernme.repair_document_timestamps import repair_zero_document_timestamps
from fernme.service import FernService
from fernme.store.sqlite_store import SQLiteStore


def test_document_timestamp_repair_is_backup_first_and_idempotent(tmp_path):
    db = tmp_path / "fictional-repair.db"
    vault = tmp_path / "vault"
    source = tmp_path / "fictional-repair.txt"
    source.write_text("# Fictional repair\n\nSynthetic evidence.\n", encoding="utf-8")
    service = FernService(
        store=SQLiteStore(str(db)),
        cfg=replace(DEFAULT, managed_documents_enabled=True),
        vault_root=str(vault),
    )
    imported = service.import_document(
        "demo.com", "elena", str(source), dry_run=False, now=0.0)
    item = imported["documents"][0]
    proposal = service.propose_tags(
        "demo.com", "elena", ["topic:synthetic"],
        document_id=item["document_id"], ts=0.0)
    service.store._conn.close()

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
            (item["document_id"],),
        ).fetchone()[0] == 1_725_000_000.0
        assert conn.execute(
            "SELECT ts FROM events WHERE type='document'"
        ).fetchone()[0] == 1_725_000_000.0
        assert conn.execute(
            "SELECT created_ts FROM canonicalization_suggestions "
            "WHERE suggestion_id=?",
            (proposal["suggestion"]["suggestion_id"],),
        ).fetchone()[0] == 1_725_000_000.0
    finally:
        conn.close()

    repeated = repair_zero_document_timestamps(db, 1_725_000_000.0)
    assert repeated["documents"] == 0
    assert repeated["events"] == 0
    assert repeated["suggestions"] == 0
