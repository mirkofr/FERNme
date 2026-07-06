import json
import os
import sqlite3
import sys
import tempfile
from dataclasses import replace

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from fernme.config import DEFAULT
from fernme.service import FernService
from fernme.store.sqlite_store import SCHEMA, SQLiteStore


PAIR = ("pref:mint", "topic:rain")


def _db_path():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    os.remove(path)
    return path


def _svc(cfg=DEFAULT):
    svc = FernService(_db_path(), cfg=cfg)
    for user in ("alex", "bea", "cora"):
        svc.consent("shop", user, True)
    return svc


def _teach(svc, user, tags, ts):
    svc.observe("shop", user, "note", {"tags": list(tags)}, ts=ts)


def test_single_user_site_card_is_byte_identical_with_default_k():
    default_svc = _svc()
    open_svc = _svc(replace(DEFAULT, assoc_min_users=1))
    events = [
        ("alex", ["topic:rain", "pref:mint"], 1.0),
        ("alex", ["pref:cedar"], 2.0),
    ]
    for svc in (default_svc, open_svc):
        for user, tags, ts in events:
            _teach(svc, user, tags, ts)

    default_card = default_svc.card(
        "shop", "alex", context=["topic:rain"], now=10.0, cold_start=False)
    open_card = open_svc.card(
        "shop", "alex", context=["topic:rain"], now=10.0, cold_start=False)

    assert json.dumps(default_card, sort_keys=True, separators=(",", ":")) == json.dumps(
        open_card, sort_keys=True, separators=(",", ":"))


def test_cross_user_suppression_and_self_visibility():
    svc = _svc()
    _teach(svc, "alex", ["topic:rain", "pref:mint"], 1.0)

    assert PAIR in svc.store.load_assoc("shop", user="alex", min_users=2).edges
    assert PAIR not in svc.store.load_assoc("shop", user="bea", min_users=2).edges
    assert PAIR not in svc.store.load_assoc("shop", min_users=2).edges

    _teach(svc, "bea", ["topic:rain", "pref:mint"], 2.0)

    assert PAIR in svc.store.load_assoc("shop", user="cora", min_users=2).edges
    assert PAIR in svc.store.load_assoc("shop", min_users=2).edges


def test_assoc_min_users_one_recovers_shared_site_behavior():
    svc = _svc(replace(DEFAULT, assoc_min_users=1))
    _teach(svc, "alex", ["topic:rain", "pref:mint"], 1.0)

    shared = svc.store.load_assoc("shop").edges
    reader = svc.store.load_assoc("shop", user="bea", min_users=svc.cfg.assoc_min_users).edges

    assert reader == shared
    assert PAIR in reader


def test_forget_everywhere_decrements_counts_and_resuppresses():
    svc = _svc()
    _teach(svc, "alex", ["topic:rain", "pref:mint"], 1.0)
    _teach(svc, "bea", ["topic:rain", "pref:mint"], 2.0)

    assert PAIR in svc.store.load_assoc("shop", user="cora", min_users=2).edges

    svc.forget_everywhere("shop", "bea")

    assert PAIR not in svc.store.load_assoc("shop", user="cora", min_users=2).edges
    assert PAIR in svc.store.load_assoc("shop", user="alex", min_users=2).edges
    row = svc.store._conn.execute(
        "SELECT users FROM assoc_edges WHERE site=? AND a=? AND b=?",
        ("shop", PAIR[0], PAIR[1]),
    ).fetchone()
    orphans = svc.store._conn.execute(
        "SELECT COUNT(*) n FROM assoc_edge_users WHERE site=? AND user=?",
        ("shop", "bea"),
    ).fetchone()["n"]
    assert row["users"] == 1
    assert orphans == 0


def test_assoc_privacy_migration_is_idempotent_and_backfills_events():
    path = _db_path()
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
    conn.execute("INSERT INTO assoc_edges VALUES(?,?,?,?)", ("shop", PAIR[0], PAIR[1], 0.5))
    conn.execute(
        "INSERT INTO events(site,user,ts,type,payload,attrs) VALUES(?,?,?,?,?,?)",
        ("shop", "alex", 1.0, "note", "{}", json.dumps([[PAIR[0], 1.0], [PAIR[1], 1.0]])),
    )
    conn.commit()
    conn.close()

    store = SQLiteStore(path)
    before_cols = [tuple(r) for r in store._conn.execute("PRAGMA table_info(assoc_edges)")]
    before_users = [dict(r) for r in store._conn.execute(
        "SELECT * FROM assoc_edge_users ORDER BY site,user,a,b")]
    store._conn.executescript(SCHEMA)
    store._migrate()
    after_cols = [tuple(r) for r in store._conn.execute("PRAGMA table_info(assoc_edges)")]
    after_users = [dict(r) for r in store._conn.execute(
        "SELECT * FROM assoc_edge_users ORDER BY site,user,a,b")]

    assert before_cols == after_cols
    assert before_users == after_users
    assert before_users == [{
        "site": "shop",
        "user": "alex",
        "a": PAIR[0],
        "b": PAIR[1],
        "hits": 1,
    }]
    assert store._conn.execute(
        "SELECT users FROM assoc_edges WHERE site=? AND a=? AND b=?",
        ("shop", PAIR[0], PAIR[1]),
    ).fetchone()["users"] == 1
