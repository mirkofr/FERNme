import importlib
import importlib.util
import os
import subprocess
import sys

import pytest

from fernme.runtime_config import default_db_path, default_site, default_user
from fernme.service import FernService


def _home_env(tmp_path):
    env = os.environ.copy()
    home = tmp_path / "home"
    env["HOME"] = str(home)
    env["USERPROFILE"] = str(home)
    env.pop("FERNME_DB", None)
    return env, home


def test_default_db_path_resolves_under_home_and_creates_on_first_service_use(tmp_path, monkeypatch):
    env, home = _home_env(tmp_path)
    monkeypatch.setenv("HOME", env["HOME"])
    monkeypatch.setenv("USERPROFILE", env["USERPROFILE"])
    monkeypatch.delenv("FERNME_DB", raising=False)

    path = default_db_path()
    assert path == str(home / ".fernme" / "fernme.db")
    assert not os.path.exists(path)

    svc = FernService()

    assert svc.store.path == path
    assert os.path.exists(path)


def test_fernme_db_site_and_user_env_overrides_are_respected(tmp_path, monkeypatch):
    db_path = tmp_path / "chosen" / "memory.db"
    monkeypatch.setenv("FERNME_DB", str(db_path))
    monkeypatch.setenv("FERNME_SITE", "demo.local")
    monkeypatch.setenv("FERNME_USER", "elena")

    svc = FernService()

    assert default_db_path() == str(db_path)
    assert default_site() == "demo.local"
    assert default_user() == "elena"
    assert svc.store.path == str(db_path)
    assert db_path.exists()


def test_mcp_print_db_path_stdout_only_and_exits_without_creating_db(tmp_path):
    db_path = tmp_path / "printed" / "memory.db"
    env = os.environ.copy()
    env["FERNME_DB"] = str(db_path)
    proc = subprocess.run(
        [sys.executable, "-m", "fernme.api.mcp_server", "--print-db-path"],
        cwd=os.path.dirname(os.path.dirname(__file__)),
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=20,
        check=True,
    )

    assert proc.stdout.strip() == str(db_path)
    assert proc.stderr == ""
    assert not db_path.exists()


@pytest.mark.skipif(importlib.util.find_spec("mcp") is None, reason="mcp extra not installed")
def test_mcp_startup_notice_uses_stderr_and_creates_default_db(tmp_path, monkeypatch, capsys):
    db_path = tmp_path / "startup" / "memory.db"
    monkeypatch.setenv("FERNME_DB", str(db_path))

    from fernme.api import mcp_server
    importlib.reload(mcp_server)

    result = mcp_server.main([], run_server=False)
    captured = capsys.readouterr()

    assert result == 0
    assert captured.out == ""
    assert str(db_path) in captured.err
    assert "FERNme DB:" in captured.err
    assert db_path.exists()
