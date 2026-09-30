"""Concurrent and failed writes must not lose or half-apply memory (SQLite)."""
import threading

import pytest

from fernme.service import FernService

SITE = "concurrency.example"


def _svc(tmp_path):
    return FernService(db_path=str(tmp_path / "c.db"))


def _run_threads(n, target):
    errors = []

    def wrapped(i):
        try:
            target(i)
        except Exception as exc:  # pragma: no cover - surfaced below
            errors.append(exc)
    threads = [threading.Thread(target=wrapped, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors, errors


def test_parallel_writes_to_one_user_keep_every_hit(tmp_path):
    svc = _svc(tmp_path)
    svc.consent(SITE, "u", True)

    def worker(i):
        for j in range(25):
            svc.observe(SITE, "u", "chat", {"tags": ["pref:tea"]}, ts=float(i * 100 + j))

    _run_threads(8, worker)
    ug = svc.store.load_user(SITE, "u")
    assert len(ug.history["pref:tea"]) == svc.cfg.history_cap   # bounded; hits carry the count
    assert ug.edges["pref:tea"].hits == 200
    assert len(svc.store.events_chronological(SITE, "u")) == 200


def test_parallel_writes_from_many_users_keep_shared_assoc_counts(tmp_path):
    svc = _svc(tmp_path)
    for i in range(6):
        svc.consent(SITE, f"u{i}", True)

    def worker(i):
        for _ in range(10):
            svc.observe(SITE, f"u{i}", "chat", {"tags": ["pref:tea", "topic:books"]})

    _run_threads(6, worker)
    rows = svc.store._conn.execute(
        "SELECT SUM(hits) n, COUNT(*) users FROM assoc_edge_users WHERE site=?",
        (SITE,)).fetchone()
    assert rows["n"] == 60 and rows["users"] == 6
    edge = svc.store._conn.execute(
        "SELECT users FROM assoc_edges WHERE site=?", (SITE,)).fetchone()
    assert edge["users"] == 6


def test_failed_write_rolls_back_graph_and_event(tmp_path, monkeypatch):
    svc = _svc(tmp_path)
    svc.consent(SITE, "u", True)
    svc.observe(SITE, "u", "chat", {"tags": ["pref:tea"]})

    def boom(_ev):
        raise RuntimeError("disk full")
    monkeypatch.setattr(svc.store, "append_event", boom)
    with pytest.raises(RuntimeError):
        svc.observe(SITE, "u", "chat", {"tags": ["pref:coffee"]})
    monkeypatch.undo()

    ug = svc.store.load_user(SITE, "u")
    assert "pref:coffee" not in ug.edges
    assert ug.edges["pref:tea"].hits == 1
    assert len(svc.store.events_chronological(SITE, "u")) == 1
    # the store is usable again after the rollback
    svc.observe(SITE, "u", "chat", {"tags": ["pref:coffee"]})
    assert "pref:coffee" in svc.store.load_user(SITE, "u").edges


def test_delta_save_matches_full_state_after_drops_and_rewrites(tmp_path):
    svc = _svc(tmp_path)
    svc.consent(SITE, "u", True)
    for t in range(5):
        svc.observe(SITE, "u", "chat", {"tags": ["pref:tea", "topic:rare"]}, ts=float(t))
    ug = svc.store.load_user(SITE, "u")
    ug.history["pref:tea"] = sorted(ug.history["pref:tea"] + [-1.0])   # non-append rewrite
    del ug.edges["topic:rare"]
    ug.history.pop("topic:rare")
    svc.store.save_user(ug)

    again = svc.store.load_user(SITE, "u")
    assert set(again.edges) == {"pref:tea"}
    assert sorted(again.history["pref:tea"]) == [-1.0, 0.0, 1.0, 2.0, 3.0, 4.0]
    assert "topic:rare" not in again.history


def test_failed_commit_rolls_back_instead_of_leaking_into_next_write(tmp_path):
    svc = _svc(tmp_path)
    svc.consent(SITE, "u", True)
    store = svc.store
    real_conn = store._conn

    class FailingCommit:
        def __init__(self, conn):
            self._c = conn
        def commit(self):
            raise __import__("sqlite3").OperationalError("disk I/O error")
        def __getattr__(self, name):
            return getattr(self._c, name)

    store._conn = FailingCommit(real_conn)
    with pytest.raises(Exception):
        svc.observe(SITE, "u", "chat", {"tags": ["pref:failed_write"]})
    store._conn = real_conn
    svc.observe(SITE, "u", "chat", {"tags": ["pref:ok"]})
    edges = svc.store.load_user(SITE, "u").edges
    assert "pref:failed_write" not in edges and "pref:ok" in edges
