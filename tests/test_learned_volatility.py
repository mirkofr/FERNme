"""Option B learned volatility. Run: pytest -q tests/test_learned_volatility.py"""
import os
import sqlite3
import sys
import tempfile
from dataclasses import replace

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from fernme.config import Config, DEFAULT
from fernme.core.graph import Edge, UserGraph
from fernme.resolution import effective_half_life_days, half_life_days, needs_verify
from fernme.service import FernService
from fernme.store.sqlite_store import SQLiteStore


def _svc(**kwargs):
    cfg = replace(DEFAULT, curation=True, learned_volatility=True, **kwargs)
    svc = FernService(store=SQLiteStore(":memory:"), cfg=cfg)
    svc.consent("s", "u", True)
    return svc


def test_learned_volatility_defaults_off():
    assert Config().learned_volatility is False


def test_sqlite_migrates_old_schema_and_round_trips_learned_stats():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        con = sqlite3.connect(path)
        con.executescript("""
        CREATE TABLE user_edges(
          site TEXT, user TEXT, attr TEXT, weight REAL, confidence REAL,
          source TEXT, last_reinforced REAL, hits INTEGER, fast REAL DEFAULT 0,
          salience REAL DEFAULT 0,
          PRIMARY KEY(site, user, attr));
        INSERT INTO user_edges VALUES('s','u','employer:oldco',5,0.9,'known',10,3,0,0);
        """)
        con.commit()
        con.close()

        store = SQLiteStore(path)
        edge = store.load_user("s", "u").edges["employer:oldco"]
        assert edge.provenance == "inferred"
        assert edge.change_count == 0
        assert edge.first_seen_ts is None

        ug = store.load_user("s", "u")
        edge = ug.edges["employer:oldco"]
        edge.provenance = "stated"
        edge.change_count = 2
        edge.first_seen_ts = 0.0
        edge.last_changed_ts = 400.0
        edge.last_change_counted_ts = 400.0
        store.save_user(ug)

        store._conn.close()
        store2 = SQLiteStore(path)
        loaded = store2.load_user("s", "u").edges["employer:oldco"]
        assert loaded.provenance == "stated"
        assert loaded.change_count == 2
        assert loaded.first_seen_ts == 0.0
        assert loaded.last_changed_ts == 400.0
        assert loaded.last_change_counted_ts == 400.0
        store2._conn.close()
    finally:
        if os.path.exists(path):
            os.remove(path)


def test_sqlite_learned_stats_migration_is_noop_when_already_migrated():
    store = SQLiteStore(":memory:")
    before_cols = [
        tuple(r) for r in store._conn.execute("PRAGMA table_info(user_edges)")
    ]
    store._migrate()
    after_cols = [
        tuple(r) for r in store._conn.execute("PRAGMA table_info(user_edges)")
    ]

    assert after_cols == before_cols


def test_stated_supersession_records_change_stats_and_persists():
    svc = _svc()
    svc.observe("s", "u", "chat", {
        "tags": ["employer:oldco"], "source": "stated",
    }, ts=0.0)
    svc.observe("s", "u", "chat", {
        "tags": ["employer:newco"], "source": "stated",
    }, ts=120.0)

    ug = svc.store.load_user("s", "u")
    edge = ug.edges["employer:newco"]
    assert edge.change_count == 1
    assert edge.first_seen_ts == 0.0
    assert edge.last_changed_ts == 120.0
    assert edge.provenance == "stated"

    again = svc.store.load_user("s", "u").edges["employer:newco"]
    assert again.change_count == 1
    assert again.last_change_counted_ts == 120.0
    exported = svc.export("s", "u")["edges"]["employer:newco"]
    assert exported["change_count"] == 1
    assert exported["provenance"] == "stated"


def test_end_to_end_frequent_stated_supersessions_shorten_half_life():
    svc = _svc(learned_volatility_prior_strength=3.0)
    for ts, attr in (
        (0.0, "employer:a"),
        (90.0, "employer:b"),
        (180.0, "employer:c"),
        (270.0, "employer:d"),
        (360.0, "employer:e"),
    ):
        svc.observe("s", "u", "chat", {"tags": [attr], "source": "stated"}, ts=ts)

    edge = svc.store.load_user("s", "u").edges["employer:e"]
    cfg = svc.cfg
    learned = effective_half_life_days("employer:e", edge, 500.0, cfg)
    prior = half_life_days("employer:e", cfg)

    assert edge.change_count == 4
    assert edge.first_seen_ts == 0.0
    assert edge.last_changed_ts == 360.0
    assert edge.last_change_counted_ts == 360.0
    assert learned < prior


def test_censoring_makes_never_changed_slot_trend_long():
    cfg = replace(DEFAULT, learned_volatility=True)
    edge = Edge(weight=5.0, confidence=0.9, hits=5, last_reinforced=0.0,
                first_seen_ts=0.0, change_count=0)
    prior = half_life_days("employer:oldco", cfg)
    learned = effective_half_life_days("employer:oldco", edge, 900.0, cfg)

    assert learned > prior
    assert learned >= 900.0


def test_old_rows_without_stats_remain_class_prior_when_flag_on():
    cfg = replace(DEFAULT, learned_volatility=True)
    edge = Edge(weight=5.0, confidence=0.9, hits=5, last_reinforced=0.0)

    assert effective_half_life_days("employer:oldco", edge, 900.0, cfg) == half_life_days(
        "employer:oldco", cfg)


def test_learned_censoring_only_applies_to_single_value_slots():
    cfg = replace(DEFAULT, learned_volatility=True)
    edge = Edge(weight=5.0, confidence=0.9, hits=5, last_reinforced=0.0,
                first_seen_ts=0.0, change_count=0)

    assert effective_half_life_days("organic", edge, 900.0, cfg) == half_life_days(
        "organic", cfg)


def test_inferred_flip_does_not_move_learned_rate():
    svc = _svc()
    svc.observe("s", "u", "chat", {
        "tags": ["employer:oldco"], "source": "stated",
    }, ts=0.0)
    out = svc.observe("s", "u", "chat", {
        "tags": ["employer:newco"], "source": "inferred",
    }, ts=200.0)

    assert out["questions"]
    edge = svc.store.load_user("s", "u").edges["employer:newco"]
    assert edge.change_count == 0
    assert edge.last_changed_ts is None


def test_burst_supersessions_are_rate_limited():
    svc = _svc(learned_min_change_interval=30.0)
    svc.observe("s", "u", "chat", {
        "tags": ["employer:a"], "source": "stated",
    }, ts=0.0)
    svc.observe("s", "u", "chat", {
        "tags": ["employer:b"], "source": "stated",
    }, ts=100.0)
    svc.observe("s", "u", "chat", {
        "tags": ["employer:c"], "source": "stated",
    }, ts=105.0)

    edge = svc.store.load_user("s", "u").edges["employer:c"]
    assert edge.change_count == 1
    assert edge.last_change_counted_ts == 100.0


def test_learned_verify_personalizes_fast_and_stable_users():
    cfg = replace(DEFAULT, learned_volatility=True, verify_age_enabled=True,
                  learned_volatility_prior_strength=1.0)
    fast = Edge(weight=5.0, confidence=0.9, hits=5, last_reinforced=860.0,
                first_seen_ts=600.0, change_count=4, last_changed_ts=860.0,
                last_change_counted_ts=860.0)
    stable = Edge(weight=5.0, confidence=0.9, hits=5, last_reinforced=0.0,
                  first_seen_ts=0.0, change_count=0)
    now = 900.0

    assert effective_half_life_days("employer:x", fast, now, cfg) < half_life_days(
        "employer:x", cfg)
    assert effective_half_life_days("employer:x", stable, now, cfg) > half_life_days(
        "employer:x", cfg)
    class_cfg = replace(cfg, learned_volatility=False)
    assert needs_verify("employer:x", fast, now, cfg)["age_halflives"] > needs_verify(
        "employer:x", fast, now, class_cfg)["age_halflives"]
    assert needs_verify("employer:x", stable, now, cfg)["age_halflives"] < needs_verify(
        "employer:x", stable, now, class_cfg)["age_halflives"]


def test_delete_and_forget_everywhere_wipe_learned_stats_with_user_edges():
    svc = _svc()
    svc.observe("s", "u", "chat", {"tags": ["employer:a"], "source": "stated"}, ts=0.0)
    svc.observe("s", "u", "chat", {"tags": ["employer:b"], "source": "stated"}, ts=100.0)
    assert svc.store.load_user("s", "u").edges["employer:b"].change_count == 1

    svc.forget_everywhere("s", "u")
    svc.consent("s", "u", True)
    svc.observe("s", "u", "chat", {"tags": ["employer:c"], "source": "stated"}, ts=200.0)

    edge = svc.store.load_user("s", "u").edges["employer:c"]
    assert edge.change_count == 0
    assert edge.first_seen_ts == 200.0

    svc.delete("s", "u")
    svc.consent("s", "u", True)
    svc.observe("s", "u", "chat", {"tags": ["employer:d"], "source": "stated"}, ts=300.0)
    assert svc.store.load_user("s", "u").edges["employer:d"].change_count == 0
