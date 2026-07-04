import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from fernme.service import FernService


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "validate_real_profile.py"


def _make_fixture_db(path):
    svc = FernService(str(path))
    svc.consent("demo.shop", "alex", True)
    for i, attr in enumerate(("person:dana", "person:dana-reyes", "person:dana-reyes-md")):
        for j in range(3):
            svc.observe("demo.shop", "alex", "note", {"tags": [attr]}, ts=i + j / 10)
    for j in range(4):
        svc.observe("demo.shop", "alex", "note", {"tags": ["topic:orbit"]}, ts=10 + j)
    for j in range(2):
        svc.observe("demo.shop", "alex", "note", {"tags": ["org:northwind"]}, ts=20 + j)
    return path


def _table_count(path, table):
    conn = sqlite3.connect(path)
    try:
        return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    finally:
        conn.close()


def test_validate_real_profile_runs_end_to_end_on_fictional_fixture(tmp_path):
    db_path = _make_fixture_db(tmp_path / "fictional_profile.db")
    map_path = tmp_path / "fictional_entity_map.yaml"
    map_path.write_text(
        """
entities:
  - id: dana
    kind: person
    display_name: Dana
    aliases:
      - person:dana
      - person:dana-reyes
      - person:dana-reyes-md
  - id: northwind
    kind: org
    display_name: NW
    aliases:
      - org:northwind
relations:
  - subject: dana
    relation: ceo_of
    object: northwind
probes:
  - id: orbit_intro
    context:
      - person:dana
      - org:northwind
    targets:
      - dana
    relations:
      - subject: dana
        relation: ceo_of
        object: northwind
""".strip(),
        encoding="utf-8",
    )
    entities_before = _table_count(db_path, "entities")

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--db",
            str(db_path),
            "--site",
            "demo.shop",
            "--user",
            "alex",
            "--entity-map",
            str(map_path),
            "--top-n",
            "8",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr + result.stdout
    report = json.loads(result.stdout)
    assert report["input_modified"] is False
    assert report["worked_on_temp_copy"] is True
    assert report["content_redacted"] is True
    assert report["fragmentation"]["tag_count"] == 5
    assert report["fragmentation"]["candidate_alias_clusters"][0]["size"] == 3
    assert "attrs" not in report["fragmentation"]["candidate_alias_clusters"][0]
    assert report["entity_map"] == {"entities": 2, "relations": 1, "probes": 1}
    assert report["probes"][0]["probe_id"] == "orbit_intro"
    assert report["probes"][0]["targets"][0]["rank_on"] is not None
    assert report["probes"][0]["relation_checks"][0]["appears_on"] is True
    assert _table_count(db_path, "entities") == entities_before


def test_validate_real_profile_refuses_mirko_named_copy_without_owner_flag(tmp_path):
    db_path = _make_fixture_db(tmp_path / "mirko_profile_copy.db")

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--db",
            str(db_path),
            "--site",
            "demo.shop",
            "--user",
            "alex",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 2
    report = json.loads(result.stdout)
    assert "refusing filenames matching mirko*" in report["error"]
    assert report["content_redacted"] is True
