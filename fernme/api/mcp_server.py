"""MCP server exposing FERNme as agent tools, so any MCP-capable agent can give a
user persistent, glass-box memory.

Run from an installed package with: fernme-mcp
Development fallback: python -m fernme.api.mcp_server
Requires: pip install fernme
"""
from __future__ import annotations
import argparse
import sys
from ..service import FernService
from ..runtime_config import default_db_path, default_site, default_user, ensure_default_db_path

svc = None


def _service() -> FernService:
    global svc
    if svc is None:
        svc = FernService()
    return svc

try:
    from mcp.server.fastmcp import FastMCP
except Exception as e:  # pragma: no cover
    FastMCP = None

if FastMCP is not None:
    mcp = FastMCP("fernme")

    @mcp.tool()
    def remember(site: str = default_site(), user: str = default_user(),
                 type: str = "note", tags: list[str] = [],
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
        return _service().observe(site, user, type, payload, ts)

    @mcp.tool()
    def recall_glossary(site: str = default_site(), user: str = default_user()) -> dict:
        """What each remembered tag MEANS: {tag: {gloss, context}}. Context is the
        sentence it came from; gloss is the supplied or templated one-liner."""
        return _service().glossary(site, user)

    @mcp.tool()
    def grant_consent(site: str = default_site(), user: str = default_user(),
                      granted: bool = True) -> dict:
        """Grant or withdraw a user's consent to be remembered on a site."""
        return _service().consent(site, user, granted)

    @mcp.tool()
    def recall_card(site: str = default_site(), user: str = default_user(),
                    context: list[str] = [], now: float = 0.0) -> dict:
        """Get the token-minimal memory card for a user (what to inject into the prompt)."""
        return _service().card(site, user, context, now)

    @mcp.tool()
    def recall_events(site: str = default_site(), user: str = default_user(),
                      contains: str = "", limit: int = 20) -> list:
        """Open the Cabinet: search a user's raw interaction history for specifics."""
        return _service().recall(site, user, contains=contains or None, limit=limit)

    @mcp.tool()
    def import_obsidian(path: str, site: str = default_site(), user: str = default_user(),
                        dry_run: bool = False,
                        max_notes: int = None, include: list[str] = [],
                        exclude: list[str] = []) -> dict:
        """Import an Obsidian vault from the MCP server machine.

        Returns a redacted count summary only. Note text is stored as data, and
        wikilinks are queued as human-reviewed suggestions rather than applied.
        """
        return _service().import_obsidian(
            site, user, path, dry_run=dry_run, max_notes=max_notes,
            include=include or None, exclude=exclude or None)

    @mcp.tool()
    def edit_memory(attr: str, weight: float, site: str = default_site(),
                    user: str = default_user()) -> dict:
        """Glass-box override of a single preference (locked, never decays)."""
        return _service().edit(site, user, attr, weight)

    @mcp.tool()
    def forget_me(site: str = default_site(), user: str = default_user()) -> dict:
        """Delete everything stored about a user on a site (right to be forgotten)."""
        return _service().delete(site, user)

    @mcp.tool()
    def list_canonicalization_suggestions(site: str = default_site(),
                                          user: str = default_user(), now: float = 0.0,
                                          refresh: bool = True) -> list[dict]:
        """List pending alias/entity canonicalization suggestions for human review."""
        return _service().list_suggestions(site, user, now, refresh)

    @mcp.tool()
    def accept_canonicalization_suggestion(suggestion_id: str,
                                           site: str = default_site(),
                                           user: str = default_user(),
                                           ts: float = 0.0) -> dict:
        """Accept one pending suggestion and apply it through the service API."""
        return _service().accept_suggestion(site, user, suggestion_id, ts)

    @mcp.tool()
    def reject_canonicalization_suggestion(suggestion_id: str,
                                           site: str = default_site(),
                                           user: str = default_user(),
                                           ts: float = 0.0) -> dict:
        """Reject one pending suggestion so it does not resurface."""
        return _service().reject_suggestion(site, user, suggestion_id, ts)

    @mcp.tool()
    def propose_entity_link(alias_attr: str, entity_id: str,
                            site: str = default_site(), user: str = default_user(),
                            ts: float = 0.0) -> dict:
        """Propose an entity alias link for human review. Never auto-applies."""
        return _service().propose_entity_link(site, user, alias_attr, entity_id, ts)

    @mcp.tool()
    def propose_tags(tags: list[str], text: str = "", source_note: str = "",
                     source_event_id: int = None,
                     site: str = default_site(), user: str = default_user(),
                     ts: float = 0.0) -> dict:
        """Propose tags inferred from text for human review. Never auto-applies.

        Use after recalling/importing Cabinet text when an agent has read prose and
        wants to turn it into memory graph tags without silently writing truth.
        """
        return _service().propose_tags(
            site, user, tags, text=text, source_note=source_note,
            source_event_id=source_event_id, ts=ts)

    @mcp.tool()
    def propose_relation(subject_id: str, relation: str, object_id: str,
                         site: str = default_site(), user: str = default_user(),
                         note: str = "", ts: float = 0.0) -> dict:
        """Propose a typed entity relation for human review. Never auto-applies."""
        return _service().propose_relation(site, user, subject_id, relation, object_id, note, ts)

def main(argv=None, run_server: bool = True):
    parser = argparse.ArgumentParser()
    parser.add_argument("--print-db-path", action="store_true",
                        help="Print the resolved FERNme SQLite DB path and exit.")
    ns = parser.parse_args(argv)
    if ns.print_db_path:
        print(default_db_path())
        return 0
    if FastMCP is None:
        raise SystemExit("Install the 'mcp' package: pip install mcp")
    resolved = ensure_default_db_path()
    global svc
    svc = FernService(db_path=resolved)
    print(f"FERNme DB: {resolved}", file=sys.stderr)
    if run_server:
        mcp.run()
    return 0

if __name__ == "__main__":
    main()
