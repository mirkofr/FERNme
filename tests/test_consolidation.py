import json
import os
import shutil
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from fernme.consolidation import (
    ConsolidationError,
    apply_consolidation,
    dry_run,
    plan_consolidation,
    require_explicit_safe_db,
    undo_consolidation,
)
from fernme.service import FernService
from fernme.vocabulary import Vocabulary


def _db_path():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    os.remove(path)
    return path


def _svc(path=None):
    path = path or _db_path()
    svc = FernService(path)
    svc.consent("site", "user", True)
    return svc, path


def _backup(path):
    backup = path + ".layer3-backup"
    shutil.copy2(path, backup)
    os.utime(backup, None)
    return backup


def _dump_tables(path):
    svc = FernService(path)
    conn = svc.store._conn
    return {
        "user_edges": [dict(r) for r in conn.execute(
            "SELECT * FROM user_edges ORDER BY site,user,attr"
        )],
        "user_history": [dict(r) for r in conn.execute(
            "SELECT * FROM user_history ORDER BY site,user,attr,ts"
        )],
        "assoc_edges": [dict(r) for r in conn.execute(
            "SELECT * FROM assoc_edges ORDER BY site,a,b"
        )],
    }


def _row_count(path, table):
    svc = FernService(path)
    return svc.store._conn.execute(f"SELECT COUNT(*) n FROM {table}").fetchone()["n"]


def test_dry_run_writes_nothing():
    svc, path = _svc()
    svc.observe("site", "user", "note", {"tags": ["alpha_alias", "peer"]}, ts=1)
    before = _dump_tables(path)

    vocab = Vocabulary.from_spec({"person:alpha": ["alpha_alias"]})
    report = dry_run(path, vocab)

    assert report["mode"] == "dry-run"
    assert report["groups"] == 1
    assert _dump_tables(path) == before


def test_merge_correctness_weights_summed_and_neighbors_unioned():
    svc, path = _svc()
    svc.observe("site", "user", "note", {"tags": ["alpha_alias", "topic:x"]}, ts=1)
    svc.observe("site", "user", "note", {"tags": ["person:alpha", "topic:y"]}, ts=2)
    svc.observe("site", "user", "note", {"tags": ["alpha_other", "topic:y"]}, ts=3)
    vocab = Vocabulary.from_spec({
        "person:alpha": ["alpha_alias", "alpha_other"],
    })

    before_edges = svc.store.load_user("site", "user").edges
    expected_weight = sum(
        before_edges[attr].weight
        for attr in ("alpha_alias", "person:alpha", "alpha_other")
    )

    report = apply_consolidation(path, vocab, backup_path=_backup(path))
    assert report["mode"] == "apply"
    assert report["active_tags_after"] == report["active_tags_before"] - 2

    svc_after = FernService(path)
    edges = svc_after.store.load_user("site", "user").edges
    assert edges["person:alpha"].weight == expected_weight
    assert edges["alpha_alias"].source == "superseded"
    assert edges["alpha_other"].source == "superseded"

    assoc = svc_after.store.load_assoc("site").edges
    assert ("alpha_alias", "topic:x") not in assoc
    assert ("alpha_other", "topic:y") not in assoc
    assert assoc[("person:alpha", "topic:x")] > 0
    assert assoc[("person:alpha", "topic:y")] > 0


def test_undo_restores_original_graph_tables():
    svc, path = _svc()
    svc.observe("site", "user", "note", {"tags": ["alpha_alias", "topic:x"]}, ts=1)
    svc.observe("site", "user", "note", {"tags": ["alpha_other", "topic:y"]}, ts=2)
    before = _dump_tables(path)
    vocab = Vocabulary.from_spec({"person:alpha": ["alpha_alias", "alpha_other"]})

    run_id = apply_consolidation(path, vocab, backup_path=_backup(path))["run_id"]
    assert _dump_tables(path) != before

    report = undo_consolidation(path, run_id)
    assert report["mode"] == "undo"
    assert _dump_tables(path) == before
    assert _row_count(path, "consolidation_runs") == 0


def test_same_surname_entities_stay_distinct():
    svc, path = _svc()
    svc.observe("site", "user", "note", {"tags": ["reyes-dana"]}, ts=1)
    svc.observe("site", "user", "note", {"tags": ["reyes-remy"]}, ts=2)
    svc.observe("site", "user", "note", {"tags": ["reyes"]}, ts=3)
    vocab = Vocabulary.from_spec({
        "person:mrs-reyes": ["reyes-dana"],
        "person:mr-reyes": ["reyes-remy"],
    })

    apply_consolidation(path, vocab, backup_path=_backup(path))

    edges = FernService(path).store.load_user("site", "user").edges
    active = {attr for attr, edge in edges.items() if edge.source != "superseded"}
    assert "person:mrs-reyes" in active
    assert "person:mr-reyes" in active
    assert "reyes" in active
    assert "person:reyes" not in active


def test_apply_requires_backup_and_refuses_mirko_db_name():
    svc, path = _svc()
    svc.observe("site", "user", "note", {"tags": ["alpha_alias"]}, ts=1)
    vocab = Vocabulary.from_spec({"person:alpha": ["alpha_alias"]})

    with pytest.raises(ConsolidationError, match="backup"):
        apply_consolidation(path, vocab, backup_path=path + ".missing")

    blocked = os.path.join(os.path.dirname(path), "mirko.db")
    open(blocked, "wb").close()
    with pytest.raises(ConsolidationError, match="mirko.db"):
        require_explicit_safe_db(blocked)


def test_plan_report_is_aggregate_only():
    svc, path = _svc()
    svc.observe("site", "user", "note", {"tags": ["alpha_alias"]}, ts=1)
    vocab = Vocabulary.from_spec({"person:alpha": ["alpha_alias"]})

    report = plan_consolidation(svc.store, vocab).report()
    encoded = json.dumps(report)

    assert "alpha" not in encoded
    assert report["content_redacted"] is True
