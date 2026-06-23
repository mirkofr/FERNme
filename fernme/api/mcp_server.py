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
                 text: str = "", source: str = "stated", glosses: dict = {},
                 ts: float = 0.0) -> dict:
        """Record an interaction/preference for a user on a site (consent required).

        tags:    namespaced 'ns:value' tokens, e.g. 'pref:concise', 'topic:python',
                 '!likes:dairy' (leading '!' = a dislike). Prefer SPECIFIC tags.
        text:    the sentence this came from. Stored as free context (no token
                 cost) so a bare tag isn't ambiguous later.
        source:  'stated' (the user said it) or 'inferred' (you guessed it).
                 Inferred never silently overrides stated; conflicts return a
                 'questions' list to ask the user.
        glosses: optional {tag: one-line meaning}. Emit these as a byproduct of
                 your reply (a few tokens, no separate call). Missing ones fall
                 back to a deterministic namespace template (0 tokens).
        Returns stored attrs, plus 'questions'/'superseded' when curation is on."""
        payload = {"tags": tags, "source": source}
        if text:
            payload["text"] = text
        if glosses:
            payload["glosses"] = glosses
        return svc.observe(site, user, type, payload, ts)

    @mcp.tool()
    def recall_glossary(site: str, user: str) -> dict:
        """What each remembered tag MEANS: {tag: {gloss, context}}. Context is the
        sentence it came from; gloss is the supplied or templated one-liner."""
        return svc.glossary(site, user)

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
