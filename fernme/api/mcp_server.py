"""MCP server exposing FERNme as agent tools, so any MCP-capable agent can give a
user persistent, glass-box memory.

Run from an installed package with: fernme-mcp
Development fallback: python -m fernme.api.mcp_server
Requires: pip install fernme
"""
from __future__ import annotations
import argparse
import sys
from pathlib import Path

from ..capture.fernmark_documents import FernmarkDocumentError
from ..service import ConsentError, FernService
from ..runtime_config import default_db_path, default_site, default_user, ensure_default_db_path

svc = None


def _service() -> FernService:
    global svc
    if svc is None:
        svc = FernService()
    return svc


def _document_tool_error(message: str) -> dict:
    """Return a stable MCP error payload without exposing a traceback."""
    return {
        "ok": False,
        "error": str(message),
        "content_redacted": True,
    }


def _resolve_document_path(path: str) -> str:
    """Resolve an explicit user path and require an existing file or directory."""
    if not isinstance(path, str) or not path.strip():
        raise ValueError("path must name an existing regular file or directory")
    try:
        resolved = Path(path).expanduser().resolve(strict=True)
        is_regular_source = resolved.is_file() or resolved.is_dir()
    except (OSError, RuntimeError) as exc:
        raise ValueError(
            "path must name an existing regular file or directory"
        ) from exc
    if not is_regular_source:
        raise ValueError("path must name an existing regular file or directory")
    return str(resolved)


def _safe_source_name(value) -> str:
    """Keep only a bounded basename suitable for a redacted report."""
    name = Path(str(value or "document")).name
    name = "".join(ch for ch in name if ch.isprintable()).strip()
    return (name or "document")[:255]


def _safe_tag(value) -> str:
    """Bound printable tag metadata before returning it over MCP."""
    tag = "".join(ch for ch in str(value) if ch.isprintable()).strip()
    return tag[:160]


def _redacted_document_report(report: dict, confirmed: bool) -> dict:
    """Whitelist document metadata returned over MCP."""
    safe = {
        key: report[key]
        for key in (
            "dry_run", "envelopes_read", "documents_imported", "events_added",
            "tags_proposed", "tags_written", "suggestions_queued", "warnings",
            "quality", "skipped", "repeat_semantics", "content_redacted",
        )
        if key in report
    }
    safe["ok"] = True
    safe["documents"] = []
    for document in report.get("documents", []):
        source_sha256 = str(document.get("source_sha256", ""))
        item = {
            "source_name": _safe_source_name(document.get("source_name")),
            "source_sha256_prefix": source_sha256[:12],
            "quality": document.get("quality"),
            "warning_count": document.get("warning_count", 0),
            "block_count": document.get("block_count", 0),
            "tags": [
                _safe_tag(tag) for tag in document.get("tags", [])
                if isinstance(tag, str) and _safe_tag(tag)
            ],
            "status": document.get("status"),
        }
        if confirmed:
            item["source_sha256"] = source_sha256
        safe["documents"].append(item)
    return safe


def _import_document(path: str, site: str, user: str, confirm: bool = False,
                     max_bytes: int = None) -> dict:
    """Implementation shared by the MCP tool and direct safety tests."""
    try:
        resolved = _resolve_document_path(path)
    except ValueError as exc:
        return _document_tool_error(str(exc))
    try:
        report = _service().import_fernmark(
            site, user, resolved, dry_run=not confirm, max_bytes=max_bytes)
    except FernmarkDocumentError as exc:
        message = str(exc)
        if "fernme[fernmark]" in message:
            return _document_tool_error(message)
        return _document_tool_error("invalid FERNmark document envelope")
    except (OSError, TypeError, ValueError):
        return _document_tool_error("invalid document import options or envelope")
    return _redacted_document_report(report, confirmed=confirm)


def _forget_document(site: str, user: str, source_sha256: str) -> dict:
    """Forget one document while returning clean validation/consent errors."""
    try:
        return _service().forget_document(site, user, source_sha256)
    except (ConsentError, ValueError) as exc:
        return _document_tool_error(str(exc))

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
    def import_document(path: str, site: str = default_site(),
                        user: str = default_user(), confirm: bool = False,
                        max_bytes: int = None) -> dict:
        """Preview or import explicit user-named local FERNmark envelopes.

        Always call first with confirm=false and show the redacted preview to
        the user. Call again with confirm=true only after the user agrees; that
        confirmed call may grant consent and write memory. The path must be an
        explicit user-named file or directory on the MCP server machine.
        """
        return _import_document(path, site, user, confirm, max_bytes)

    @mcp.tool()
    def forget_document(source_sha256: str, site: str = default_site(),
                        user: str = default_user()) -> dict:
        """Forget one imported document by its confirmed SHA-256 identifier."""
        return _forget_document(site, user, source_sha256)

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
