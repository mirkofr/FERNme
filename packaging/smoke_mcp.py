"""Smoke test the packaged FERNme MCP server over stdio.

This script uses a temporary SQLite database and synthetic site/user labels.
"""
from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path

import anyio
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def run_smoke(command: str, args: list[str] | None = None) -> dict:
    fd, db_path = tempfile.mkstemp(prefix="fernme_mcp_smoke_", suffix=".db")
    os.close(fd)
    Path(db_path).unlink(missing_ok=True)
    env = os.environ.copy()
    env["FERNME_DB"] = db_path
    params = StdioServerParameters(
        command=command,
        args=args or [],
        env=env,
        cwd=os.getcwd(),
        encoding="utf-8",
        encoding_error_handler="replace",
    )
    try:
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = await session.list_tools()
                tool_names = sorted(tool.name for tool in tools.tools)
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
        return {
            "ok": True,
            "tools": tool_names,
            "card": [content.model_dump() for content in card.content],
        }
    finally:
        Path(db_path).unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--command", default="fernme-mcp")
    parser.add_argument("--arg", action="append", default=[])
    parser.add_argument("server_args", nargs=argparse.REMAINDER)
    ns = parser.parse_args()
    server_args = list(ns.arg)
    if ns.server_args:
        server_args.extend(arg for arg in ns.server_args if arg != "--")
    result = anyio.run(run_smoke, ns.command, server_args)
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
