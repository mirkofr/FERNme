"""MCP photo tool tests with generated fictional images and temporary stores."""
from __future__ import annotations

from dataclasses import replace
from io import BytesIO
import importlib.util
import json
from pathlib import Path
import sys

import pytest

from fernme.api import mcp_server
from fernme.config import DEFAULT
from fernme.capture.config import default_config, write_config
from fernme.service import FernService
from fernme.store.sqlite_store import SQLiteStore


requires_pillow = pytest.mark.skipif(
    importlib.util.find_spec("PIL") is None,
    reason="Pillow media extra is not installed",
)


def _service(tmp_path, monkeypatch, enabled=True):
    service = FernService(
        store=SQLiteStore(str(tmp_path / "mcp-photo.db")),
        cfg=replace(DEFAULT, media_enabled=enabled),
    )
    monkeypatch.setattr(mcp_server, "svc", service)
    return service


def _write_photo(path):
    from PIL import Image

    output = BytesIO()
    Image.new("RGB", (10, 8), "purple").save(output, format="PNG")
    path.write_bytes(output.getvalue())
    return path


def test_disabled_photo_tool_returns_clean_error_before_path_access(
        tmp_path, monkeypatch):
    _service(tmp_path, monkeypatch, enabled=False)

    report = mcp_server.remember_photo(
        "missing.png", ["topic:fictional"], "demo.com", "elena")

    assert report == {
        "ok": False,
        "error": "media memory is disabled",
        "content_redacted": True,
    }


def test_mcp_service_reads_default_off_media_settings_from_fern_toml(
        tmp_path, monkeypatch):
    config = default_config()
    config["media"] = {
        "enabled": True, "max_bytes": 12345, "thumbnail_max_px": 96}
    write_config(config, str(tmp_path / "fern.toml"))
    monkeypatch.chdir(tmp_path)

    service = mcp_server._configured_service(str(tmp_path / "configured.db"))

    assert service.cfg.media_enabled is True
    assert service.cfg.media_max_bytes == 12345
    assert service.cfg.media_thumbnail_max_px == 96
    assert service.media_root == tmp_path / "configured.assets"


@requires_pillow
def test_photo_preview_is_no_write_then_confirm_imports_and_forget_deletes(
        tmp_path, monkeypatch):
    photo = _write_photo(tmp_path / "fictional-photo.png")
    service = _service(tmp_path, monkeypatch)
    description = "Fictional purple sample body must stay private."

    preview = mcp_server.remember_photo(
        str(photo), ["topic:purple"], "demo.com", "elena",
        description, False, False)

    assert preview["ok"] is True and preview["dry_run"] is True
    assert preview["id"] is None and preview["thumbnail_uri"] is None
    assert len(preview["sha256_prefix"]) == 12
    assert "sha256" not in preview
    assert service.store.has_consent("demo.com", "elena") is False
    assert service.store.list_assets("demo.com", "elena") == []
    assert not (tmp_path / "mcp-photo.assets").exists()
    assert description not in json.dumps(preview)

    denied = mcp_server.remember_photo(
        str(photo), ["topic:purple"], "demo.com", "elena",
        description, False, True)
    assert denied["ok"] is False and "no consent" in denied["error"]

    service.consent("demo.com", "elena", True)
    confirmed = mcp_server.remember_photo(
        str(photo), ["topic:purple"], "demo.com", "elena",
        description, False, True)
    asset = service.get_asset("demo.com", "elena", confirmed["id"])
    pointers = [Path(asset["uri"]), Path(asset["thumbnail_uri"])]

    assert confirmed["ok"] is True and confirmed["dry_run"] is False
    assert confirmed["id"] and confirmed["thumbnail_uri"]
    assert description not in json.dumps(confirmed)
    forgotten = mcp_server.forget_photo(
        confirmed["id"], "demo.com", "elena")
    assert forgotten["forgotten"] is True
    assert all(not pointer.exists() for pointer in pointers)
    assert service.recall_assets("demo.com", "elena") == []


def test_missing_pillow_extra_is_clean_and_names_install_extra(
        tmp_path, monkeypatch):
    service = _service(tmp_path, monkeypatch)
    service.consent("demo.com", "elena", True)
    source = tmp_path / "placeholder.png"
    source.write_bytes(b"fictional-placeholder")
    monkeypatch.setitem(sys.modules, "PIL", None)

    report = mcp_server.remember_photo(
        str(source), ["topic:test"], "demo.com", "elena", confirm=False)

    assert report["ok"] is False
    assert "fernme[media]" in report["error"]
    assert "Pillow>=10" in report["error"]
    assert "Traceback" not in json.dumps(report)


@pytest.mark.parametrize("hostile_path", [
    "missing/photo.png",
    "missing/../still-missing.png",
    r"\\.\NUL",
    "bad\x00name.png",
])
@requires_pillow
def test_hostile_photo_paths_return_clean_errors(
        hostile_path, tmp_path, monkeypatch):
    _service(tmp_path, monkeypatch)

    report = mcp_server.remember_photo(
        hostile_path, ["topic:test"], "demo.com", "elena", confirm=False)

    assert report["ok"] is False
    assert "existing regular image file" in report["error"]
    assert "Traceback" not in json.dumps(report)
