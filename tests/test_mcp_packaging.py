import importlib.util
import json
import os
import sys
import tomllib
from pathlib import Path

import anyio
import pytest


ROOT = Path(__file__).resolve().parents[1]
TEST_RELEASE_TAG = "0.4.0-beta.1"
PACKAGE_VERSION = "0.4.0b1"
UVX_FROM = f"fernme[mcp] @ git+https://github.com/mirkofr/FERNme@{TEST_RELEASE_TAG}"


def _read_json(path):
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def _assert_uvx_git_mcp(mcp):
    server = mcp["mcpServers"]["fernme"]
    assert server["command"] == "uvx"
    assert server["args"] == ["--from", UVX_FROM, "fernme-mcp"]
    assert "[mcp]" in server["args"][1]
    assert f"git+https://github.com/mirkofr/FERNme@{TEST_RELEASE_TAG}" in server["args"][1]


def test_packaging_json_files_are_valid():
    json_files = sorted((ROOT / "packaging").rglob("*.json"))
    json_files.append(ROOT / ".claude-plugin/marketplace.json")
    for path in json_files:
        json.loads(path.read_text(encoding="utf-8"))


def test_console_script_and_plugin_manifests_reference_mcp_server():
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert pyproject["project"]["version"] == PACKAGE_VERSION
    assert pyproject["project"]["scripts"]["fernme-mcp"] == "fernme.api.mcp_server:main"

    codex_plugin = _read_json(
        "packaging/codex/plugins/fernme-memory/.codex-plugin/plugin.json")
    codex_mcp = _read_json("packaging/codex/plugins/fernme-memory/.mcp.json")
    codex_local_mcp = _read_json(
        "packaging/codex/plugins/fernme-memory/.mcp.local.json")
    codex_marketplace = _read_json("packaging/codex/.agents/plugins/marketplace.json")

    assert codex_plugin["name"] == "fernme-memory"
    assert codex_plugin["version"] == TEST_RELEASE_TAG
    assert codex_plugin["skills"] == "./skills/"
    assert codex_plugin["mcpServers"] == "./.mcp.json"
    _assert_uvx_git_mcp(codex_mcp)
    assert codex_local_mcp["mcpServers"]["fernme"]["command"] == "fernme-mcp"
    assert codex_marketplace["plugins"][0]["source"]["path"] == "./plugins/fernme-memory"

    claude_plugin = _read_json(
        "packaging/claude/plugins/fernme-memory/.claude-plugin/plugin.json")
    claude_mcp = _read_json("packaging/claude/plugins/fernme-memory/.mcp.json")
    claude_local_mcp = _read_json(
        "packaging/claude/plugins/fernme-memory/.mcp.local.json")
    claude_marketplace = _read_json("packaging/claude/.claude-plugin/marketplace.json")
    root_claude_marketplace = _read_json(".claude-plugin/marketplace.json")

    assert claude_plugin["name"] == "fernme-memory"
    assert claude_plugin["version"] == TEST_RELEASE_TAG
    assert claude_plugin["skills"] == "./skills/"
    _assert_uvx_git_mcp(claude_mcp)
    assert claude_local_mcp["mcpServers"]["fernme"]["command"] == "fernme-mcp"
    assert claude_marketplace["plugins"][0]["source"] == "./plugins/fernme-memory"
    assert root_claude_marketplace["interface"]["displayName"] == "FERNme Local"
    root_source = root_claude_marketplace["plugins"][0]["source"]
    assert root_source == "./packaging/claude/plugins/fernme-memory"
    assert (ROOT / root_source).is_dir()
    assert (
        ROOT / "packaging/codex/plugins/fernme-memory/skills/fernme-memory/SKILL.md"
    ).read_text(encoding="utf-8") == (
        ROOT / "packaging/claude/plugins/fernme-memory/skills/fernme-memory/SKILL.md"
    ).read_text(encoding="utf-8")


@pytest.mark.skipif(importlib.util.find_spec("mcp") is None, reason="mcp extra not installed")
def test_mcp_stdio_smoke_remember_to_recall_card(tmp_path):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    async def run():
        db_path = tmp_path / "smoke.db"
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
                assert "remember" in {tool.name for tool in tools.tools}
                await session.call_tool(
                    "grant_consent",
                    {"site": "demo.local", "user": "elena", "granted": True},
                )
                await session.call_tool(
                    "remember",
                    {
                        "site": "demo.local",
                        "user": "elena",
                        "type": "note",
                        "tags": ["pref:concise"],
                        "text": "Elena prefers concise updates.",
                        "ts": 1.0,
                    },
                )
                card = await session.call_tool(
                    "recall_card",
                    {
                        "site": "demo.local",
                        "user": "elena",
                        "context": ["pref:concise"],
                        "now": 2.0,
                    },
                )
                assert "pref:concise" in card.content[0].text

    anyio.run(run)
