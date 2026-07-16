import os
import types

from fernme.api import serve


def test_launcher_defaults_to_local_graph_url():
    args = serve.build_parser().parse_args([])

    assert args.host == "127.0.0.1"
    assert args.port == 8077
    assert serve.target_url(args) == "http://127.0.0.1:8077/ui/graph"


def test_launcher_applies_runtime_env_without_baked_in_paths(monkeypatch):
    monkeypatch.delenv("FERNME_DB", raising=False)
    monkeypatch.delenv("FERNME_SITE", raising=False)
    monkeypatch.delenv("FERNME_USER", raising=False)
    args = serve.build_parser().parse_args([
        "--db", "redacted-db-value",
        "--site", "personal",
        "--user", "local-user",
    ])

    serve.apply_env(args)

    assert os.environ["FERNME_DB"] == "redacted-db-value"
    assert os.environ["FERNME_SITE"] == "personal"
    assert os.environ["FERNME_USER"] == "local-user"


def test_launcher_invokes_uvicorn_with_rest_app(monkeypatch):
    calls = []

    def fake_run(app, **kwargs):
        calls.append((app, kwargs))

    monkeypatch.setitem(__import__("sys").modules, "uvicorn", types.SimpleNamespace(run=fake_run))

    rc = serve.main(["--host", "127.0.0.1", "--port", "9000", "--no-open"])

    assert rc == 0
    assert calls == [("fernme.api.rest:app", {"host": "127.0.0.1", "port": 9000, "reload": False})]
