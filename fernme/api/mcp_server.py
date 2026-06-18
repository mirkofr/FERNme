"""MCP server exposing FERN as agent tools, so any MCP-capable agent (incl.
Claude) can give a user persistent, glass-box memory. Run: python -m fern.api.mcp_server
Requires: pip install mcp"""
from __future__ import annotations
import os
from ..service import FernService

svc = FernService()  # default: $FERNME_DB or ~/.fernme/fernme.db

try:
    from mcp.server.fastmcp import FastMCP
except Exception as e:  # pragma: no cover
    FastMCP = None

if FastMCP is not None:
    mcp = FastMCP("fernme")

    @mcp.tool()
    def remember(site: str, user: str, type: str = "note", tags: list[str] = [],
                 ts: float = 0.0) -> dict:
        """Record an interaction/preference for a user on a site (consent required)."""
        return svc.observe(site, user, type, {"tags": tags}, ts)

    @mcp.tool()
    def grant_consent(site: str, user: str, granted: bool = True) -> dict:
        """Grant or withdraw a user's consent to be remembered on a site."""
        return svc.consent(site, user, granted)

    @mcp.tool()
    def recall_card(site: str, user: str, context: list[str] = [], now: float = 0.0) -> dict:
        """Get the token-minimal memory card for a user (what to inject into the prompt)."""
        return svc.card(site, user, context, now)

    @mcp.tool()
    def recall_events(site: str, user: str, contains: str = "", limit: int = 20) -> list:
        """Open the Cabinet: search a user's raw interaction history for specifics."""
        return svc.recall(site, user, contains=contains or None, limit=limit)

    @mcp.tool()
    def edit_memory(site: str, user: str, attr: str, weight: float) -> dict:
        """Glass-box override of a single preference (locked, never decays)."""
        return svc.edit(site, user, attr, weight)

    @mcp.tool()
    def forget_me(site: str, user: str) -> dict:
        """Delete everything stored about a user on a site (right to be forgotten)."""
        return svc.delete(site, user)

    def main():
        mcp.run()
else:
    def main():
        raise SystemExit("Install the 'mcp' package: pip install mcp")

if __name__ == "__main__":
    main()
