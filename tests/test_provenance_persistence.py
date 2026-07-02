import os
import shutil
import sqlite3
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from fernme.consolidation import apply_consolidation, undo_consolidation
from fernme.core.graph import Edge, UserGraph
from fernme.store.sqlite_store import SQLiteStore
from fernme.vocabulary import Vocabulary


def _db_path():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    os.remove(path)
    return path


def _backup(path):
    backup = path + ".phase1-backup"
    shutil.copy2(path, backup)
    os.utime(backup, None)
    return backup


def test_sqlite_round_trips_edge_provenance_after_reopen():
    path = _db_path()
    store = SQLiteStore(path)
    ug = UserGraph("demo", "alex")
    ug.edges["pref:quiet"] = Edge(weight=2.0, confidence=0.5, provenance="stated")
    ug.edges["topic:maps"] = Edge(weight=1.0, confidence=0.2, provenance="inferred")

    store.save_user(ug)

    loaded = SQLiteStore(path).load_user("demo", "alex")
    assert loaded.edges["pref:quiet"].provenance == "stated"
    assert loaded.edges["topic:maps"].provenance == "inferred"


def test_sqlite_migrates_old_user_edges_schema_with_default_provenance():
    path = _db_path()
    conn = sqlite3.connect(path)
    conn.executescript("""
    CREATE TABLE user_edges(
      site TEXT, user TEXT, attr TEXT, weight REAL, confidence REAL,
      source TEXT, last_reinforced REAL, hits INTEGER, fast REAL DEFAULT 0,
      salience REAL DEFAULT 0, PRIMARY KEY(site, user, attr));
    CREATE TABLE user_numeric(site TEXT, user TEXT, key TEXT, value TEXT, PRIMARY KEY(site, user, key));
    CREATE TABLE user_history(site TEXT, user TEXT, attr TEXT, ts REAL);
    """)
    conn.execute(
        "INSERT INTO user_edges VALUES(?,?,?,?,?,?,?,?,?,?)",
        ("demo", "alex", "topic:maps", 1.5, 0.4, "known", 3.0, 2, 0.25, 0.75),
    )
    conn.commit()
    conn.close()

    store = SQLiteStore(path)
    cols = {r[1] for r in store._conn.execute("PRAGMA table_info(user_edges)")}
    loaded = store.load_user("demo", "alex")

    assert "provenance" in cols
    assert loaded.edges["topic:maps"].provenance == "inferred"
    assert loaded.edges["topic:maps"].weight == 1.5


def test_consolidation_preserves_and_promotes_provenance():
    path = _db_path()
    store = SQLiteStore(path)
    ug = UserGraph("demo", "alex")
    ug.edges["person:dana"] = Edge(weight=1.0, confidence=0.3, hits=1, provenance="inferred")
    ug.edges["person:dana-reyes"] = Edge(weight=2.0, confidence=0.4, hits=1, provenance="stated")
    ug.history["person:dana"] = [1.0]
    ug.history["person:dana-reyes"] = [2.0]
    store.save_user(ug)
    vocab = Vocabulary.from_spec({"person:dana-canonical": ["person:dana", "person:dana-reyes"]})

    run_id = apply_consolidation(path, vocab, backup_path=_backup(path))["run_id"]
    after = SQLiteStore(path).load_user("demo", "alex").edges

    assert after["person:dana-canonical"].provenance == "stated"
    assert after["person:dana"].provenance == "inferred"
    assert after["person:dana-reyes"].provenance == "stated"

    undo_consolidation(path, run_id)
    restored = SQLiteStore(path).load_user("demo", "alex").edges
    assert restored["person:dana"].provenance == "inferred"
    assert restored["person:dana-reyes"].provenance == "stated"


def test_postgres_round_trips_edge_provenance_if_server_available():
    pgserver = pytest.importorskip("pgserver")
    from fernme.store.postgres_store import PostgresStore

    data_dir = tempfile.mkdtemp(prefix="pgdata_provenance_")
    srv = pgserver.get_server(data_dir)
    try:
        store = PostgresStore(srv.get_uri())
        ug = UserGraph("demo", "alex")
        ug.edges["pref:quiet"] = Edge(weight=2.0, confidence=0.5, provenance="stated")
        ug.edges["topic:maps"] = Edge(weight=1.0, confidence=0.2, provenance="inferred")
        store.save_user(ug)

        loaded = PostgresStore(srv.get_uri()).load_user("demo", "alex")
        assert loaded.edges["pref:quiet"].provenance == "stated"
        assert loaded.edges["topic:maps"].provenance == "inferred"
    finally:
        srv.cleanup()
        shutil.rmtree(data_dir, ignore_errors=True)
