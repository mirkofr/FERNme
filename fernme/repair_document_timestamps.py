"""Repair epoch-zero timestamps created by early managed-document MCP tools.

The repair is opt-in, dry-run by default, and SQLite-only. Apply mode requires
a fresh backup path and a caller-selected replacement timestamp. Audit rows are
not rewritten because their timestamps are covered by the audit hash chain.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import sqlite3
from typing import Dict, Iterable, Set, Tuple


class TimestampRepairError(RuntimeError):
    pass


def _valid_timestamp(value: float) -> float:
    value = float(value)
    if not math.isfinite(value) or value <= 0:
        raise TimestampRepairError("--timestamp must be a finite value greater than zero")
    return value


def _payload(value) -> Dict:
    try:
        parsed = json.loads(value or "{}")
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _attrs(value) -> Iterable[str]:
    try:
        parsed = json.loads(value or "[]")
    except (TypeError, ValueError):
        return []
    out = []
    for item in parsed if isinstance(parsed, list) else []:
        if isinstance(item, (list, tuple)) and item:
            out.append(str(item[0]))
    return out


def _linked(payload: Dict, document_ids: Set[str], hashes: Set[str]) -> bool:
    return (
        str(payload.get("document_id") or "") in document_ids or
        str(payload.get("source_sha256") or "") in hashes
    )


def _collect(conn: sqlite3.Connection) -> Dict:
    conn.row_factory = sqlite3.Row
    documents = conn.execute(
        "SELECT document_id,site,user,source_sha256,created_ts,imported_ts "
        "FROM documents"
    ).fetchall()
    document_ids = {str(row["document_id"]) for row in documents}
    hashes = {str(row["source_sha256"]) for row in documents}
    zero_documents = [
        row for row in documents
        if float(row["created_ts"]) <= 0 or float(row["imported_ts"]) <= 0
    ]

    events = []
    edge_keys: Set[Tuple[str, str, str]] = set()
    for row in conn.execute(
            "SELECT id,site,user,payload,attrs FROM events WHERE ts<=0"):
        if not _linked(_payload(row["payload"]), document_ids, hashes):
            continue
        events.append(int(row["id"]))
        for attr in _attrs(row["attrs"]):
            edge_keys.add((str(row["site"]), str(row["user"]), attr))

    suggestions = []
    for row in conn.execute(
            "SELECT suggestion_id,payload FROM canonicalization_suggestions "
            "WHERE created_ts<=0"):
        if _linked(_payload(row["payload"]), document_ids, hashes):
            suggestions.append(str(row["suggestion_id"]))

    tag_keys = [
        (str(row["document_id"]), str(row["tag"]))
        for row in conn.execute(
            "SELECT document_id,tag FROM document_tags WHERE approved_ts<=0")
        if str(row["document_id"]) in document_ids
    ]
    zero_edges = [
        key for key in edge_keys
        if conn.execute(
            "SELECT 1 FROM user_edges WHERE site=? AND user=? AND attr=? "
            "AND last_reinforced<=0",
            key,
        ).fetchone() is not None
    ]
    zero_history = [
        key for key in edge_keys
        if conn.execute(
            "SELECT 1 FROM user_history WHERE site=? AND user=? AND attr=? AND ts<=0",
            key,
        ).fetchone() is not None
    ]
    return {
        "documents": [str(row["document_id"]) for row in zero_documents],
        "events": events,
        "suggestions": suggestions,
        "document_tags": tag_keys,
        "user_edges": zero_edges,
        "user_history": zero_history,
    }


def repair_zero_document_timestamps(
        db_path, replacement_ts: float, apply: bool = False,
        backup_path=None) -> Dict:
    """Preview or repair document-linked epoch-zero SQLite timestamps."""
    replacement_ts = _valid_timestamp(replacement_ts)
    db = Path(db_path).expanduser().resolve(strict=True)
    backup = None
    if apply:
        if backup_path is None:
            raise TimestampRepairError("--backup is required with --apply")
        backup = Path(backup_path).expanduser().resolve(strict=False)
        if backup.exists():
            raise TimestampRepairError("--backup must name a new file")
        if not backup.parent.is_dir():
            raise TimestampRepairError("--backup parent directory must exist")

    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    try:
        plan = _collect(conn)
        report = {
            "mode": "apply" if apply else "dry-run",
            "replacement_ts": replacement_ts,
            "documents": len(plan["documents"]),
            "events": len(plan["events"]),
            "suggestions": len(plan["suggestions"]),
            "document_tags": len(plan["document_tags"]),
            "user_edges": len(plan["user_edges"]),
            "user_history": len(plan["user_history"]),
            "audit_rows_changed": 0,
        }
        if not apply:
            return report

        backup_conn = sqlite3.connect(str(backup))
        try:
            conn.backup(backup_conn)
        finally:
            backup_conn.close()

        conn.execute("BEGIN IMMEDIATE")
        for document_id in plan["documents"]:
            conn.execute(
                "UPDATE documents SET "
                "created_ts=CASE WHEN created_ts<=0 THEN ? ELSE created_ts END,"
                "imported_ts=CASE WHEN imported_ts<=0 THEN ? ELSE imported_ts END "
                "WHERE document_id=?",
                (replacement_ts, replacement_ts, document_id),
            )
        for event_id in plan["events"]:
            conn.execute("UPDATE events SET ts=? WHERE id=? AND ts<=0",
                         (replacement_ts, event_id))
        for suggestion_id in plan["suggestions"]:
            conn.execute(
                "UPDATE canonicalization_suggestions SET created_ts=? "
                "WHERE suggestion_id=? AND created_ts<=0",
                (replacement_ts, suggestion_id),
            )
        for document_id, tag in plan["document_tags"]:
            conn.execute(
                "UPDATE document_tags SET approved_ts=? "
                "WHERE document_id=? AND tag=? AND approved_ts<=0",
                (replacement_ts, document_id, tag),
            )
        for site, user, attr in plan["user_edges"]:
            conn.execute(
                "UPDATE user_edges SET last_reinforced=? "
                "WHERE site=? AND user=? AND attr=? AND last_reinforced<=0",
                (replacement_ts, site, user, attr),
            )
        for site, user, attr in plan["user_history"]:
            conn.execute(
                "UPDATE user_history SET ts=? "
                "WHERE site=? AND user=? AND attr=? AND ts<=0",
                (replacement_ts, site, user, attr),
            )
        conn.commit()
        return report
    except Exception:
        if conn.in_transaction:
            conn.rollback()
        raise
    finally:
        conn.close()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Repair document-linked epoch-zero timestamps in SQLite.")
    parser.add_argument("--db", required=True, help="SQLite database to inspect.")
    parser.add_argument(
        "--timestamp", required=True, type=float,
        help="Explicit Unix timestamp to use for zero-valued document records.")
    parser.add_argument("--apply", action="store_true", help="Write the repair.")
    parser.add_argument(
        "--backup", help="Fresh SQLite backup path, required with --apply.")
    return parser


def main(argv=None) -> int:
    args = _parser().parse_args(argv)
    report = repair_zero_document_timestamps(
        args.db, args.timestamp, apply=args.apply, backup_path=args.backup)
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
