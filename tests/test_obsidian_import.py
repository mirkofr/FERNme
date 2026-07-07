import importlib.util
import json
import os
import sys
import tempfile
from pathlib import Path

import anyio
import pytest

from fernme.service import ConsentError, FernService


ROOT = Path(__file__).resolve().parents[1]


def _db_path():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    os.remove(path)
    return path


def _write_note(path: Path, text: str, mtime: float = 1_700_000_000.0) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    os.utime(path, (mtime, mtime))


def _vault(tmp_path: Path) -> Path:
    vault = tmp_path / "fictional_vault"
    _write_note(
        vault / "People" / "Mira Vale.md",
        """---
title: Mira Vale
kind: person
aliases:
  - M. Vale
tags: [pref:concise, topic:field-notes]
project: Atlas Journal
---
# Profile
Mira prefers concise updates and keeps project notes in dated bullets.
Contact mira@example.test on 2026-04-10.
She works with [[Jonas Reed|Jonas]] on [[Atlas Journal]].
- Keep decisions traceable.
""",
    )
    _write_note(
        vault / "People" / "Jonas Reed.md",
        """---
title: Jonas Reed
kind: person
aliases: [J. Reed]
tags: [topic:field-notes]
---
# Profile
Jonas reviews notes with Mira.
""",
    )
    _write_note(
        vault / "Projects" / "Atlas Journal.md",
        """---
title: Atlas Journal
kind: project
tags: [project:atlas-journal]
---
# Project
Atlas Journal keeps the team memory checklist.
""",
    )
    return vault


def _svc():
    svc = FernService(_db_path())
    svc.consent("demo.local", "elena", True)
    return svc


def test_import_obsidian_imports_tags_events_candidates_and_structured_fields(tmp_path):
    svc = _svc()
    report = svc.import_obsidian("demo.local", "elena", str(_vault(tmp_path)), now=10.0)

    assert report["content_redacted"] is True
    assert report["notes_read"] == 3
    assert report["events_added"] == 3
    assert report["structured_fields"] >= 2
    assert report["candidates_found"] >= 3
    assert report["candidates_queued"] >= 3

    edges = svc.store.load_user("demo.local", "elena").edges
    assert "person:mira-vale" in edges
    assert "person:jonas-reed" in edges
    assert "project:atlas-journal" in edges
    assert "pref:concise" in edges
    for structural in ["importer", "import_id", "source_note", "linked_note", "has_section"]:
        assert structural not in edges

    events = svc.recall("demo.local", "elena", type="obsidian_note", limit=10)
    mira = next(ev for ev in events if ev["payload"]["source_note"] == "People/Mira Vale.md")
    assert "Mira prefers concise updates" in mira["payload"]["text"]
    assert ["email", "mira@example.test"] in mira["payload"]["structured"]
    assert ["iso-date", "2026-04-10"] in mira["payload"]["structured"]

    rows = svc.store.list_suggestions("demo.local", "elena", status="pending")
    assert any(row["payload"].get("source") == "obsidian_import" for row in rows)
    assert any(row["payload"].get("alias_attr") == "person:jonas" for row in rows)
    assert svc.store.entity_by_alias("demo.local", "elena", "person:jonas") is None


def test_import_obsidian_is_idempotent_by_note_path_and_mtime(tmp_path):
    svc = _svc()
    vault = _vault(tmp_path)

    first = svc.import_obsidian("demo.local", "elena", str(vault), now=10.0)
    second = svc.import_obsidian("demo.local", "elena", str(vault), now=11.0)

    assert first["events_added"] == 3
    assert second["events_added"] == 0
    assert second["skipped"]["already_imported"] == 3
    assert len(svc.recall("demo.local", "elena", type="obsidian_note", limit=10)) == 3


def test_import_obsidian_dry_run_writes_nothing(tmp_path):
    svc = _svc()

    report = svc.import_obsidian(
        "demo.local", "elena", str(_vault(tmp_path)), dry_run=True, now=10.0)

    assert report["dry_run"] is True
    assert report["notes_read"] == 3
    assert report["events_added"] == 0
    assert report["candidates_found"] >= 3
    assert report["candidates_queued"] == 0
    assert svc.recall("demo.local", "elena", type="obsidian_note", limit=10) == []
    assert svc.store.list_suggestions("demo.local", "elena") == []
    assert svc.store.load_user("demo.local", "elena").edges == {}


def test_import_obsidian_include_exclude_and_max_notes(tmp_path):
    svc = _svc()

    report = svc.import_obsidian(
        "demo.local",
        "elena",
        str(_vault(tmp_path)),
        include=["People/*"],
        exclude=["People/Jonas*"],
        max_notes=1,
        now=10.0,
    )

    assert report["notes_read"] == 1
    assert report["skipped"]["include"] == 1
    assert report["skipped"]["exclude"] == 1
    assert report["skipped"]["cap"] == 0
    events = svc.recall("demo.local", "elena", type="obsidian_note", limit=10)
    assert [ev["payload"]["source_note"] for ev in events] == ["People/Mira Vale.md"]


def test_import_obsidian_consent_gate(tmp_path):
    svc = FernService(_db_path())

    with pytest.raises(ConsentError):
        svc.import_obsidian("demo.local", "elena", str(_vault(tmp_path)))


@pytest.mark.skipif(importlib.util.find_spec("mcp") is None, reason="mcp extra not installed")
def test_mcp_import_obsidian_round_trip_is_redacted(tmp_path):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    async def run():
        db_path = tmp_path / "mcp_obsidian.db"
        env = os.environ.copy()
        env["FERNME_DB"] = str(db_path)
        params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "fernme.api.mcp_server"],
            env=env,
            cwd=str(ROOT),
            encoding="utf-8",
            encoding_error_handler="replace",
        )
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = await session.list_tools()
                assert "import_obsidian" in {tool.name for tool in tools.tools}
                denied = await session.call_tool(
                    "import_obsidian",
                    {"site": "demo.local", "user": "elena", "path": str(_vault(tmp_path))},
                )
                assert denied.isError
                await session.call_tool(
                    "grant_consent",
                    {"site": "demo.local", "user": "elena", "granted": True},
                )
                result = await session.call_tool(
                    "import_obsidian",
                    {"site": "demo.local", "user": "elena", "path": str(_vault(tmp_path))},
                )
                text = result.content[0].text
                report = json.loads(text)
                assert report["content_redacted"] is True
                assert report["events_added"] == 3
                assert report["candidates_queued"] >= 3
                assert "Mira prefers concise updates" not in text
                assert "mira@example.test" not in text
                assert "Jonas reviews notes" not in text

    anyio.run(run)
