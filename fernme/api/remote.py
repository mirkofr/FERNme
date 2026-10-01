"""Remote MCP access for cloud agents (OpenAI dots, xAI Grok Bot, Meta Muse, ...).

Cloud agents cannot start a local stdio process; they reach MCP servers over
HTTPS. ``fernme-mcp --transport http`` serves the same tools over MCP
streamable HTTP with three guards:

* **Per-agent bearer tokens.** Each agent gets its own token
  (``fernme-mcp --add-client NAME``). Only a SHA-256 hash is stored, in
  ``clients.json`` next to the database (0600).
* **Profile lock per token.** A token is bound to one ``site``/``user``; every
  tool refuses any other profile, so one agent cannot read another agent's
  memory. Give each agent (each Grok Bot, each dot) its own site to mirror
  per-agent memory; share across agents only through the default-deny
  supernode.
* **Owner-approved consent.** Over HTTP, consent defaults to the inbox: an agent
  can only request it, and the owner approves in the FERNme app.

The engine does not depend on this module; it only adapts the MCP server.
"""
from __future__ import annotations

import contextvars
import hashlib
import hmac
import json
import os
import re
import secrets
import time
from pathlib import Path
from typing import Dict, List, Optional

from ..runtime_config import default_db_path

# (site, user, client name) for the request being served; None outside HTTP.
REQUEST_CLIENT: contextvars.ContextVar = contextvars.ContextVar("fernme_request_client",
                                                               default=None)
_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,62}$")


def clients_path() -> Path:
    override = os.environ.get("FERNME_CLIENTS")
    if override:
        return Path(override).expanduser()
    return Path(default_db_path()).with_name("clients.json")


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def load_clients(path: Optional[Path] = None) -> List[Dict]:
    path = path or clients_path()
    if not path.is_file():
        return []
    data = json.loads(path.read_text("utf-8") or "[]")
    return [c for c in data if isinstance(c, dict) and "token_sha256" in c]


def _save_clients(clients: List[Dict], path: Optional[Path] = None) -> None:
    path = path or clients_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f".{os.getpid()}.tmp")
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(clients, fh, indent=2)
    os.replace(str(tmp), str(path))


def add_client(name: str, site: Optional[str] = None, user: str = "owner",
               path: Optional[Path] = None) -> Dict:
    """Register an agent; returns its token once (only the hash is kept)."""
    name = name.strip().lower()
    if not _NAME_RE.match(name):
        raise ValueError("client name: lowercase letters, digits, '.', '_' or '-'")
    clients = [c for c in load_clients(path) if c["name"] != name]
    token = "fmk_" + secrets.token_urlsafe(32)
    entry = {"name": name, "site": site or name, "user": user or "owner",
             "token_sha256": _hash(token), "created": int(time.time())}
    clients.append(entry)
    _save_clients(clients, path)
    return {**{k: v for k, v in entry.items() if k != "token_sha256"}, "token": token}


def remove_client(name: str, path: Optional[Path] = None) -> bool:
    clients = load_clients(path)
    kept = [c for c in clients if c["name"] != name.strip().lower()]
    _save_clients(kept, path)
    return len(kept) != len(clients)


def client_for_token(token: str, clients: List[Dict]) -> Optional[Dict]:
    digest = _hash(token)
    match = None
    for c in clients:                       # compare every entry: no timing shortcut
        if hmac.compare_digest(digest, c["token_sha256"]):
            match = c
    return match


class BearerAuth:
    """ASGI middleware: require a registered client's bearer token and bind the
    request to that client's profile. ``/healthz`` stays open."""

    def __init__(self, app, clients_file: Optional[Path] = None):
        self.app = app
        self.clients_file = clients_file

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        if scope.get("path") == "/healthz":
            return await _json(send, 200, {"ok": True, "service": "fernme-mcp"})
        headers = {k.decode("latin-1").lower(): v.decode("latin-1")
                   for k, v in scope.get("headers", [])}
        auth = headers.get("authorization", "")
        token = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
        client = client_for_token(token, load_clients(self.clients_file)) if token else None
        if client is None:
            return await _json(send, 401, {"error": "missing or invalid bearer token"},
                               {"www-authenticate": "Bearer"})
        reset = REQUEST_CLIENT.set((client["site"], client["user"], client["name"]))
        try:
            return await self.app(scope, receive, send)
        finally:
            REQUEST_CLIENT.reset(reset)


async def _json(send, status: int, body: Dict, extra: Optional[Dict] = None) -> None:
    payload = json.dumps(body).encode("utf-8")
    headers = [(b"content-type", b"application/json"),
               (b"content-length", str(len(payload)).encode())]
    headers += [(k.encode(), v.encode()) for k, v in (extra or {}).items()]
    await send({"type": "http.response.start", "status": status, "headers": headers})
    await send({"type": "http.response.body", "body": payload})


def build_http_app(server_factory, groups, clients_file: Optional[Path] = None):
    """Streamable-HTTP ASGI app for the given tool groups, behind BearerAuth.

    The SDK's own DNS-rebinding check is turned off because a tunnel or proxy
    sends its public host name; the bearer token is what protects the server."""
    from mcp.server.transport_security import TransportSecuritySettings
    security = TransportSecuritySettings(enable_dns_rebinding_protection=False)
    try:                                     # mcp 1.x: settings on the server
        server = server_factory(groups, stateless_http=True, transport_security=security)
        app = server.streamable_http_app()
    except TypeError:                        # mcp 2.x: settings on the app
        server = server_factory(groups)
        app = server.streamable_http_app(stateless_http=True, transport_security=security)
    return BearerAuth(app, clients_file), server
