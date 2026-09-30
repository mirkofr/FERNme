"""MCP SDK compatibility: the server must load on mcp 1.x and 2.x, and fail clearly otherwise."""
import importlib.metadata as md

import pytest

pytest.importorskip("mcp")

from fernme.api import mcp_server


def test_supported_sdk_resolves_a_server_class():
    server_cls, error = mcp_server._load_fastmcp()
    assert server_cls is not None, error
    assert error is None
    assert callable(getattr(server_cls, "tool"))
    assert callable(getattr(server_cls, "run"))
    assert mcp_server.FastMCP is server_cls


def test_missing_package_message_names_the_install_extra(monkeypatch):
    def missing(_name):
        raise md.PackageNotFoundError("mcp")

    monkeypatch.setattr(md, "version", missing)
    msg = mcp_server._mcp_unavailable_message(ImportError("No module named 'mcp'"))
    assert "not installed" in msg
    assert 'fernme[mcp]' in msg


def test_incompatible_package_message_reports_version_not_missing(monkeypatch):
    monkeypatch.setattr(md, "version", lambda _name: "9.0.0")
    msg = mcp_server._mcp_unavailable_message(ModuleNotFoundError("renamed"))
    assert "9.0.0" in msg
    assert "not supported" in msg
    assert "not installed" not in msg
    assert "mcp>=1.0,<3" in msg


def test_main_exits_with_actionable_message_when_sdk_unusable(monkeypatch, tmp_path):
    monkeypatch.setenv("FERNME_DB", str(tmp_path / "unused.db"))
    monkeypatch.setattr(mcp_server, "FastMCP", None)
    monkeypatch.setattr(mcp_server, "_FASTMCP_IMPORT_ERROR", ModuleNotFoundError("renamed"))
    monkeypatch.setattr(md, "version", lambda _name: "9.0.0")
    with pytest.raises(SystemExit) as exc:
        mcp_server.main([], run_server=False)
    assert "9.0.0" in str(exc.value)
    assert not (tmp_path / "unused.db").exists()
