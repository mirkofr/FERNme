import json
import os
import shutil
import sqlite3
import sys
import tempfile
from dataclasses import replace

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from fernme.config import DEFAULT
from fernme.consolidation import apply_consolidation, undo_consolidation
from fernme.service import ConsentError, FernService
from fernme.store.sqlite_store import SQLiteStore
from fernme.vocabulary import Vocabulary


def _db_path():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    os.remove(path)
    return path


def _svc(cfg=DEFAULT):
    path = _db_path()
    svc = FernService(path, cfg=cfg)
    svc.consent("demo", "alex", True)
    return svc, path


def _backup(path):
    backup = path + ".phase3-backup"
    shutil.copy2(path, backup)
    os.utime(backup, None)
    return backup


def _create_pre_entity_schema_db(path):
    conn = sqlite3.connect(path)
    conn.executescript("""
    CREATE TABLE consents(site TEXT, user TEXT, granted INTEGER, ts REAL, PRIMARY KEY(site, user));
    CREATE TABLE user_edges(
      site TEXT, user TEXT, attr TEXT, weight REAL, confidence REAL,
      source TEXT, last_reinforced REAL, hits INTEGER, fast REAL DEFAULT 0,
      salience REAL DEFAULT 0, provenance TEXT NOT NULL DEFAULT 'inferred',
      PRIMARY KEY(site, user, attr));
    CREATE TABLE user_numeric(site TEXT, user TEXT, key TEXT, value TEXT, PRIMARY KEY(site, user, key));
    CREATE TABLE user_history(site TEXT, user TEXT, attr TEXT, ts REAL);
    CREATE TABLE assoc_edges(site TEXT, a TEXT, b TEXT, weight REAL, PRIMARY KEY(site, a, b));
    CREATE TABLE events(id INTEGER PRIMARY KEY AUTOINCREMENT, site TEXT, user TEXT, ts REAL, type TEXT, payload TEXT, attrs TEXT);
    CREATE TABLE prior_node(site TEXT, attr TEXT, sum REAL, n INTEGER, PRIMARY KEY(site, attr));
    CREATE TABLE prior_meta(site TEXT PRIMARY KEY, n_users INTEGER);
    CREATE TABLE identities(person TEXT, site TEXT, local_user TEXT, ts REAL, PRIMARY KEY(person, site, local_user));
    CREATE TABLE share_policy(person TEXT, target_site TEXT, category TEXT, allowed INTEGER, PRIMARY KEY(person, target_site, category));
    CREATE TABLE audit(site TEXT, user TEXT, seq INTEGER, ts REAL, action TEXT, detail TEXT, prev_hash TEXT, hash TEXT, PRIMARY KEY(site, user, seq));
    """)
    conn.execute("INSERT INTO consents VALUES(?,?,?,?)", ("demo", "alex", 1, 0.0))
    rows = [
        ("demo", "alex", "person:dana", 1.25, 0.4, "known", 1.0, 1, 0.0, 0.0, "stated"),
        ("demo", "alex", "person:dana-reyes", 1.75, 0.5, "known", 2.0, 1, 0.0, 0.0, "stated"),
        ("demo", "alex", "topic:orbit", 1.0, 0.3, "known", 2.0, 1, 0.0, 0.0, "inferred"),
    ]
    conn.executemany("INSERT INTO user_edges VALUES(?,?,?,?,?,?,?,?,?,?,?)", rows)
    conn.executemany("INSERT INTO user_history VALUES(?,?,?,?)", [
        ("demo", "alex", "person:dana", 1.0),
        ("demo", "alex", "person:dana-reyes", 2.0),
    ])
    conn.execute("INSERT INTO assoc_edges VALUES(?,?,?,?)",
                 ("demo", "person:dana", "topic:orbit", 0.5))
    conn.commit()
    conn.close()


def _dump_graph_tables(path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        return {
            "user_edges": [dict(r) for r in conn.execute(
                "SELECT * FROM user_edges ORDER BY site,user,attr")],
            "user_history": [dict(r) for r in conn.execute(
                "SELECT * FROM user_history ORDER BY site,user,attr,ts")],
            "assoc_edges": [dict(r) for r in conn.execute(
                "SELECT * FROM assoc_edges ORDER BY site,a,b")],
        }
    finally:
        conn.close()


def test_entity_crud_recall_path_and_forget_cascade():
    svc, _ = _svc()
    svc.observe("demo", "alex", "note", {"tags": ["person:dana"]}, ts=1.0)
    dana = svc.entity_create("demo", "alex", "person", "Dana Reyes")
    felix = svc.entity_create("demo", "alex", "person", "Felix Tan")
    northwind = svc.entity_create("demo", "alex", "org", "Northwind Ltd")
    svc.entity_link_alias("demo", "alex", dana, "person:dana")
    svc.entity_set_field("demo", "alex", dana, "email", "dana@example.test", ts=2.0)
    svc.entity_relate("demo", "alex", dana, "ceo_of", northwind, note="founded the team", ts=3.0)
    svc.entity_relate("demo", "alex", dana, "friend_of", felix, ts=4.0)
    svc.entity_relate("demo", "alex", felix, "works_at", northwind, ts=5.0)

    card = svc.recall_entity("demo", "alex", "person:dana")
    assert card["display_name"] == "Dana Reyes"
    assert card["fields"][0]["value"] == "dana@example.test"
    assert {r["display_relation"] for r in card["relations"]} >= {"ceo_of", "friend_of"}
    assert svc.recall_path("demo", "alex", dana, northwind)

    report = svc.entity_forget("demo", "alex", dana)

    assert report["remaining_refs"] == 0
    assert svc.store.count_entity_references(dana) == 0
    assert svc.store.load_user("demo", "alex").edges["person:dana"].source == "superseded"
    assert any(row["action"] == "forget" for row in svc.audit_log("demo", "alex"))
    assert not svc.recall_path("demo", "alex", felix, northwind, max_hops=2) or all(
        dana not in {step["from_id"] for step in path} | {step["next_id"] for step in path}
        for path in svc.recall_path("demo", "alex", felix, northwind, max_hops=2)
    )


def test_entity_write_paths_are_consent_gated():
    svc = FernService(_db_path())

    with pytest.raises(ConsentError):
        svc.entity_create("demo", "alex", "person", "Dana Reyes")


def test_relation_reinforcement_bumps_existing_row_without_duplicate():
    svc, _ = _svc()
    dana = svc.entity_create("demo", "alex", "person", "Dana Reyes")
    northwind = svc.entity_create("demo", "alex", "org", "Northwind Ltd")

    first = svc.entity_relate("demo", "alex", dana, "ceo_of", northwind, ts=1.0)
    second = svc.entity_relate("demo", "alex", dana, "ceo_of", northwind, ts=2.0)

    assert second["hits"] == first["hits"] + 1
    assert second["weight"] > first["weight"]
    assert len(svc.store.list_entity_relations("demo", "alex")) == 1


def test_relation_decay_drops_inferred_but_floor_sticks_stated():
    svc, _ = _svc(cfg=replace(DEFAULT, lam=1.0))
    dana = svc.entity_create("demo", "alex", "person", "Dana Reyes")
    felix = svc.entity_create("demo", "alex", "person", "Felix Tan")
    northwind = svc.entity_create("demo", "alex", "org", "Northwind Ltd")
    orbit = svc.entity_create("demo", "alex", "org", "Orbit Labs")
    svc.entity_relate("demo", "alex", dana, "ceo_of", northwind, provenance="stated", ts=0.0)
    svc.entity_relate("demo", "alex", felix, "works_at", orbit, provenance="inferred", ts=0.0)

    report = svc.decay("demo", "alex", now=10.0)
    rows = svc.store.list_entity_relations("demo", "alex")

    assert report["dropped_relations"] == 1
    assert len(rows) == 1
    assert rows[0]["relation"] == "ceo_of"
    assert rows[0]["weight"] == DEFAULT.floor


def test_display_field_and_note_data_are_sanitized_and_capped():
    svc, _ = _svc()
    dana = svc.entity_create("demo", "alex", "person", "Dana\nReyes\x00" + "x" * 100)
    northwind = svc.entity_create("demo", "alex", "org", "Northwind Ltd")
    field = svc.entity_set_field("demo", "alex", dana, "phone", "555\n0101\x00" + "x" * 200)
    row = svc.entity_relate("demo", "alex", dana, "ceo_of", northwind,
                            note="note\nwith\x00controls " + "x" * 300)
    card = svc.recall_entity("demo", "alex", dana)

    assert "\n" not in card["display_name"]
    assert "\x00" not in card["display_name"]
    assert len(card["display_name"]) <= 80
    assert "\n" not in field["value"]
    assert len(field["value"]) <= 128
    assert "\n" not in row["note"]
    assert len(row["note"]) <= 280


def test_flags_off_card_output_byte_identical_after_entity_rows_added():
    svc, _ = _svc()
    svc.observe("demo", "alex", "note", {"tags": ["pref:quiet", "topic:maps"]}, ts=1.0)
    before_card = svc.card("demo", "alex", context=["maps"], now=2.0)
    before = json.dumps(before_card, sort_keys=True, separators=(",", ":"))
    dana = svc.entity_create("demo", "alex", "person", "Dana Reyes")
    northwind = svc.entity_create("demo", "alex", "org", "Northwind Ltd")
    svc.entity_link_alias("demo", "alex", dana, "pref:quiet")
    svc.entity_set_field("demo", "alex", dana, "email", "dana@example.test")
    svc.entity_relate("demo", "alex", dana, "ceo_of", northwind)
    after_card = svc.card("demo", "alex", context=["maps"], now=2.0)
    after = json.dumps(after_card, sort_keys=True, separators=(",", ":"))

    assert svc.cfg.entities is False
    assert svc.cfg.entity_aggregation is False
    assert "card_token_estimate" not in after_card
    assert after == before


def test_sqlite_migrates_pre_entity_schema_without_losing_graph_data():
    path = _db_path()
    _create_pre_entity_schema_db(path)

    store = SQLiteStore(path)
    tables = {r["name"] for r in store._conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    edges = store.load_user("demo", "alex").edges

    assert {"entities", "entity_aliases", "entity_fields", "entity_relations"} <= tables
    assert edges["person:dana"].weight == 1.25
    assert edges["person:dana-reyes"].provenance == "stated"


def test_undo_consolidation_works_on_pre_entity_schema_snapshot():
    path = _db_path()
    _create_pre_entity_schema_db(path)
    before = _dump_graph_tables(path)
    vocab = Vocabulary.from_spec({
        "person:dana-canonical": ["person:dana", "person:dana-reyes"],
    })

    run_id = apply_consolidation(path, vocab, backup_path=_backup(path))["run_id"]
    assert _dump_graph_tables(path) != before
    report = undo_consolidation(path, run_id)

    assert report["mode"] == "undo"
    assert _dump_graph_tables(path) == before
