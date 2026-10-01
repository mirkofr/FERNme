"""Remote MCP over streamable HTTP for cloud agents: per-agent tokens, per-token
profile lock, owner-approved consent. Real server subprocess; fictional data."""
import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import anyio
import pytest

pytest.importorskip("mcp")
pytest.importorskip("uvicorn")

from fernme.api import remote
from fernme.service import FernService

ROOT = Path(__file__).resolve().parents[1]


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture()
def server(tmp_path):
    db = tmp_path / "remote.db"
    clients = tmp_path / "clients.json"
    grok = remote.add_client("grok-bot", site="grok-legal", user="owner", path=clients)
    dots = remote.add_client("openai-dots", user="owner", path=clients)
    port = _free_port()
    env = {**os.environ, "FERNME_DB": str(db), "FERNME_CLIENTS": str(clients)}
    for var in ("FERNME_SITE", "FERNME_USER", "FERNME_MCP_TOOLS", "FERNME_REMOTE_CONSENT"):
        env.pop(var, None)
    proc = subprocess.Popen(
        [sys.executable, "-m", "fernme.api.mcp_server", "--transport", "http",
         "--port", str(port)], cwd=str(ROOT), env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    base = f"http://127.0.0.1:{port}"
    for _ in range(100):
        try:
            urllib.request.urlopen(base + "/healthz", timeout=0.5)
            break
        except Exception:
            time.sleep(0.1)
    else:
        proc.kill()
        pytest.fail("remote MCP server did not start")
    yield {"url": base + "/mcp", "base": base, "grok": grok, "dots": dots, "db": db}
    proc.terminate()
    proc.wait(timeout=10)


def _call(url, token, steps):
    from mcp import ClientSession
    from mcp.client.streamable_http import create_mcp_http_client, streamable_http_client

    async def run():
        client = create_mcp_http_client(headers={"Authorization": f"Bearer {token}"})
        async with client:
            async with streamable_http_client(url, http_client=client) as streams:
                async with ClientSession(streams[0], streams[1]) as session:
                    await session.initialize()
                    return await steps(session)
    return anyio.run(run)


def _text(result):
    return json.loads(result.content[0].text)


def _is_error(result):
    return bool(getattr(result, "is_error", getattr(result, "isError", False)))


def test_requests_without_a_valid_token_are_refused(server):
    for headers in ({}, {"Authorization": "Bearer fmk_wrong"}):
        req = urllib.request.Request(server["url"], data=b"{}", headers=headers, method="POST")
        with pytest.raises(urllib.error.HTTPError) as exc:
            urllib.request.urlopen(req, timeout=5)
        assert exc.value.code == 401


def test_agent_gets_its_own_profile_and_owner_approves_consent(server):
    token = server["grok"]["token"]

    async def ask(session):
        tools = {t.name for t in (await session.list_tools()).tools}
        consent = _text(await session.call_tool("grant_consent", {"confirm": True}))
        return tools, consent
    tools, consent = _call(server["url"], token, ask)
    assert "remember" in tools and "import_document" not in tools
    assert "import_obsidian" not in tools and "accept_canonicalization_suggestion" not in tools
    assert consent["pending"] is True and consent["site"] == "grok-legal"

    owner = FernService(db_path=str(server["db"]))
    assert owner.consent_requests()[0]["requested_by"] == "grok-bot"
    owner.decide_consent_request("grok-legal", "owner", approve=True)

    async def use(session):
        await session.call_tool("remember", {"tags": ["pref:concise"], "ts": 1.0})
        card = _text(await session.call_tool("recall_card", {"now": 2.0}))
        other = await session.call_tool("recall_card", {"site": "openai-dots", "now": 2.0})
        return card, other
    card, other = _call(server["url"], token, use)
    assert "pref:concise" in card["wire"]
    assert _is_error(other)


def test_two_agents_do_not_see_each_others_memory(server):
    owner = FernService(db_path=str(server["db"]))
    for name, site in (("grok-bot", "grok-legal"), ("openai-dots", "openai-dots")):
        owner.consent(site, "owner", True)

    async def grok(session):
        await session.call_tool("remember", {"tags": ["topic:contract-dispute"], "ts": 1.0})
    _call(server["url"], server["grok"]["token"], grok)

    async def dots(session):
        return _text(await session.call_tool("recall_card", {"now": 2.0}))
    card = _call(server["url"], server["dots"]["token"], dots)
    assert "contract-dispute" not in card["wire"]


def test_client_registry_stores_only_hashes(tmp_path):
    path = tmp_path / "clients.json"
    entry = remote.add_client("muse", path=path)
    raw = path.read_text()
    assert entry["token"] not in raw and entry["site"] == "muse"
    assert remote.client_for_token(entry["token"], remote.load_clients(path))["name"] == "muse"
    assert remote.remove_client("muse", path=path)
    assert remote.load_clients(path) == []
    with pytest.raises(ValueError):
        remote.add_client("Bad Name!", path=path)
