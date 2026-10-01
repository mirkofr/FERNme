import importlib.util
import json
import os
import sys
from pathlib import Path

import anyio
import pytest

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib


ROOT = Path(__file__).resolve().parents[1]
EXPECTED_PACKAGE_VERSION = "0.4.1"
PACKAGE_VERSION = tomllib.loads(
    (ROOT / "pyproject.toml").read_text(encoding="utf-8")
)["project"]["version"]
TEST_RELEASE_TAG = f"v{PACKAGE_VERSION}"
UVX_FROM = f"fernme[mcp] @ git+https://github.com/mirkofr/FERNme@{TEST_RELEASE_TAG}"
FERNMARK_VCS = (
    "fernmark @ git+https://github.com/mirkofr/FERNmark.git@"
    "23e16ea5b01f4ce77fee81b5bf4f7e0d87d77bae")
PLUGIN_VERSION = PACKAGE_VERSION
CORE_TOOLS = {
    "remember", "recall_glossary", "grant_consent", "recall_card", "recall_events",
    "import_obsidian", "edit_memory", "forget_me", "list_canonicalization_suggestions",
    "accept_canonicalization_suggestion", "reject_canonicalization_suggestion",
    "propose_entity_link", "propose_tags", "propose_relation",
    "record_outcome", "why", "export_memory",
    "set_setting", "get_settings", "clear_setting",
}
DOCUMENT_TOOLS = {
    "import_document", "forget_document", "recall_documents", "archive_document",
    "supersede_document", "set_document_flags", "remember_document_use",
    "read_document", "backfill_documents",
}
PHOTO_TOOLS = {"remember_photo", "forget_photo"}


def _read_json(path):
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def _assert_uvx_git_mcp(mcp, server_name="fernme", tools="core", fernmark=False):
    server = mcp["mcpServers"][server_name]
    assert server["command"] == "uvx"
    expected = (["--with", FERNMARK_VCS] if fernmark else []) + [
        "--from", UVX_FROM, "fernme-mcp", "--tools", tools]
    assert server["args"] == expected
    assert f"git+https://github.com/mirkofr/FERNme@{TEST_RELEASE_TAG}" in UVX_FROM
    assert server["env"]["FERNME_DB"] == ""
    return server


def test_packaging_json_files_are_valid():
    json_files = sorted((ROOT / "packaging").rglob("*.json"))
    json_files.append(ROOT / ".claude-plugin/marketplace.json")
    for path in json_files:
        json.loads(path.read_text(encoding="utf-8"))


def test_console_script_and_plugin_manifests_reference_mcp_server():
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert PACKAGE_VERSION == EXPECTED_PACKAGE_VERSION
    assert pyproject["project"]["version"] == PACKAGE_VERSION
    init_text = (ROOT / "fernme/__init__.py").read_text(encoding="utf-8")
    assert f'__version__ = "{PACKAGE_VERSION}"' in init_text
    assert pyproject["project"]["scripts"]["fernme-mcp"] == "fernme.api.mcp_server:main"
    assert pyproject["project"]["scripts"]["fernme-ui"] == "fernme.api.serve:main"
    assert "mcp>=1.0,<3" in pyproject["project"]["dependencies"]
    assert pyproject["project"]["optional-dependencies"]["mcp"] == ["mcp>=1.0,<3"]
    assert pyproject["project"]["readme"] == "README.md"
    assert pyproject["project"]["license"] == {"text": "Apache-2.0"}
    package_data = pyproject["tool"]["setuptools"]["package-data"]["fernme"]
    assert "web/static/*.js" in pyproject["tool"]["setuptools"]["package-data"]["fernme"]
    assert "web/static/app/*" in package_data
    assert "web/static/app/assets/*" in package_data
    assert "Development Status :: 4 - Beta" in pyproject["project"]["classifiers"]
    assert "Homepage" in pyproject["project"]["urls"]
    assert pyproject["project"]["optional-dependencies"]["ui"] == [
        "fastapi>=0.110", "uvicorn[standard]>=0.27"]
    assert pyproject["project"]["optional-dependencies"]["fernmark"] == [
        FERNMARK_VCS]
    assert pyproject["project"]["optional-dependencies"]["media"] == [
        "Pillow>=10"]

    for host in ("codex", "claude"):
        base = f"packaging/{host}/plugins"
        # the main plugin is memory only: no FERNmark, no document or photo tools
        core = _assert_uvx_git_mcp(_read_json(f"{base}/fernme-memory/.mcp.json"))
        assert "FERNME_MANAGED_DOCUMENTS" not in core["env"]
        local = _read_json(f"{base}/fernme-memory/.mcp.local.json")["mcpServers"]["fernme"]
        assert local["command"] == "fernme-mcp" and local["args"] == ["--tools", "core"]
        # the optional add-on serves documents and photos from the same database
        docs = _assert_uvx_git_mcp(_read_json(f"{base}/fernme-docs/.mcp.json"),
                                   server_name="fernme-docs", tools="documents,photos",
                                   fernmark=True)
        assert docs["env"]["FERNME_MANAGED_DOCUMENTS"] == "true"
        docs_local = _read_json(f"{base}/fernme-docs/.mcp.local.json")["mcpServers"]["fernme-docs"]
        assert docs_local["args"] == ["--tools", "documents,photos"]

    codex_plugin = _read_json(
        "packaging/codex/plugins/fernme-memory/.codex-plugin/plugin.json")
    codex_docs = _read_json("packaging/codex/plugins/fernme-docs/.codex-plugin/plugin.json")
    codex_marketplace = _read_json("packaging/codex/.agents/plugins/marketplace.json")
    assert codex_plugin["name"] == "fernme-memory"
    assert codex_plugin["version"] == PLUGIN_VERSION == codex_docs["version"]
    assert codex_plugin["skills"] == "./skills/"
    assert codex_plugin["mcpServers"] == "./.mcp.json"
    assert codex_plugin["interface"]["capabilities"] == ["MCP", "Memory"]
    assert "Managed Document Evidence" in codex_docs["interface"]["capabilities"]
    assert "Photo Memory" in codex_docs["interface"]["capabilities"]
    assert [p["source"]["path"] for p in codex_marketplace["plugins"]] == [
        "./plugins/fernme-memory", "./plugins/fernme-docs"]

    claude_plugin = _read_json(
        "packaging/claude/plugins/fernme-memory/.claude-plugin/plugin.json")
    claude_docs = _read_json("packaging/claude/plugins/fernme-docs/.claude-plugin/plugin.json")
    claude_marketplace = _read_json("packaging/claude/.claude-plugin/marketplace.json")
    root_claude_marketplace = _read_json(".claude-plugin/marketplace.json")
    assert claude_plugin["name"] == "fernme-memory" and claude_docs["name"] == "fernme-docs"
    assert claude_plugin["version"] == PLUGIN_VERSION == claude_docs["version"]
    assert claude_plugin["skills"] == "./skills/"
    assert [p["source"] for p in claude_marketplace["plugins"]] == [
        "./plugins/fernme-memory", "./plugins/fernme-docs"]
    assert root_claude_marketplace["interface"]["displayName"] == "FERNme Local"
    for plugin in root_claude_marketplace["plugins"]:
        assert (ROOT / plugin["source"]).is_dir()

    for name in ("fernme-memory", "fernme-docs"):
        codex_text = (ROOT / f"packaging/codex/plugins/{name}/skills/{name}/SKILL.md"
                      ).read_text(encoding="utf-8")
        assert codex_text == (ROOT / f"packaging/claude/plugins/{name}/skills/{name}/SKILL.md"
                              ).read_text(encoding="utf-8")
    skill_text = (ROOT / "packaging/claude/plugins/fernme-memory/skills/fernme-memory/SKILL.md"
                  ).read_text(encoding="utf-8")
    docs_text = (ROOT / "packaging/claude/plugins/fernme-docs/skills/fernme-docs/SKILL.md"
                 ).read_text(encoding="utf-8")
    for tool in ("recall_card", "remember", "propose_tags", "new Codex task", "fernme-docs"):
        assert tool in skill_text
    for tool in DOCUMENT_TOOLS | PHOTO_TOOLS:
        assert tool not in skill_text
    for phrase in ("import_document", "forget_document", "recall_documents", "document_id",
                   "review is pending", "confirm=false", "remember_photo", "forget_photo",
                   "fernme[media]"):
        assert phrase in docs_text


@pytest.mark.skipif(importlib.util.find_spec("mcp") is None, reason="mcp extra not installed")
def test_mcp_stdio_smoke_remember_to_recall_card(tmp_path):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    async def run():
        db_path = tmp_path / "smoke.db"
        env = os.environ.copy()
        env["FERNME_DB"] = str(db_path)
        env["FERNME_MCP_TOOLS"] = "all"
        params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "fernme.api.mcp_server"],
            env=env,
            cwd=str(ROOT),
            encoding="utf-8",
            encoding_error_handler="replace",
        )
        with open(os.devnull, "w", encoding="utf-8") as errlog:
            async with stdio_client(params, errlog=errlog) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    tools = await session.list_tools()
                    tool_names = {tool.name for tool in tools.tools}
                    assert "remember" in tool_names
                    assert "import_document" in tool_names
                    assert "forget_document" in tool_names
                    assert "recall_documents" in tool_names
                    assert "archive_document" in tool_names
                    assert "supersede_document" in tool_names
                    assert "remember_photo" in tool_names
                    assert "forget_photo" in tool_names
                    await session.call_tool(
                        "grant_consent",
                        {"site": "demo.local", "user": "elena", "granted": True, "confirm": True},
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


@pytest.mark.skipif(importlib.util.find_spec("mcp") is None, reason="mcp extra not installed")
def test_tool_groups_keep_the_default_server_small(monkeypatch):
    import asyncio
    from fernme.api import mcp_server as server

    def names(groups):
        tools = asyncio.run(server.build_server(groups).list_tools())
        return {tool.name for tool in tools}

    assert names({"core"}) == CORE_TOOLS
    assert names({"documents", "photos"}) == DOCUMENT_TOOLS | PHOTO_TOOLS
    assert names(set(server.TOOL_GROUPS)) == CORE_TOOLS | DOCUMENT_TOOLS | PHOTO_TOOLS

    monkeypatch.delenv("FERNME_MCP_TOOLS", raising=False)
    monkeypatch.delenv("FERNME_MANAGED_DOCUMENTS", raising=False)
    assert server.resolve_tool_groups() == {"core"}
    monkeypatch.setenv("FERNME_MANAGED_DOCUMENTS", "true")
    assert server.resolve_tool_groups() == {"core", "documents"}
    assert server.resolve_tool_groups("core") == {"core"}
    assert server.resolve_tool_groups("all") == set(server.TOOL_GROUPS)
    with pytest.raises(SystemExit):
        server.resolve_tool_groups("everything")
