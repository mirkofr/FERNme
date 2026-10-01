"""Per-install secret for the audit chain and the private prior's noise.

The audit chain used to be keyed with a constant that is public in the source,
so anyone with database access could rewrite history and still pass
``verify_audit``. The key now comes from, in order:

0. an explicit ``FernService(secret_key=...)`` (host applications that keep
   secrets in their own vault);
1. ``FERNME_SECRET_KEY`` (any string; set the same value on every process that
   shares a database, e.g. a Postgres deployment). ``FERNME_AUDIT_KEY`` is
   accepted as an alias;
2. a key file next to a SQLite database (``<db>.key``, created with 0600
   permissions on first use) so the MCP server, the UI and the CLI that share one
   database also share one key, while the key does not live inside the database;
3. for Postgres, a secret stored once in the database (``fernme_secret``) so
   every server process agrees; set ``FERNME_SECRET_KEY`` to keep it outside;
4. a random per-process key for in-memory databases.

Keep the ``.key`` file with its database: a database restored without it gets a
new key, and chains written under the old one then fail ``verify_audit``.

Backward compatibility: when the key file is first created for a SQLite
database that already has audit entries, the file records ``audit=legacy`` and
the audit chain keeps using the legacy constant so existing chains still
verify; ``verify_audit`` then reports ``legacy_key: True``. The secret itself is
still new and keys the private prior's noise.
"""
from __future__ import annotations

import hashlib
import os
import secrets
import sys
import time
from pathlib import Path
from typing import Tuple

LEGACY_AUDIT_KEY = b"fernme-default-audit-key"
ENV_VAR = "FERNME_SECRET_KEY"
ENV_ALIASES = (ENV_VAR, "FERNME_AUDIT_KEY")


def _key_path_for(store) -> Path | None:
    path = getattr(store, "path", None)
    if not path or path == ":memory:" or str(path).startswith("file::memory:"):
        return None
    return Path(str(path) + ".key")


def _has_audit_rows(store) -> bool:
    conn = getattr(store, "_conn", None)
    if conn is None:
        return False
    try:
        return conn.execute("SELECT 1 FROM audit LIMIT 1").fetchone() is not None
    except Exception:
        return False


def _read_key_file(path: Path) -> Tuple[bytes, bool]:
    for _ in range(50):                      # another process may be mid-create
        lines = path.read_text("ascii").split()
        if lines:
            return bytes.fromhex(lines[0]), "audit=legacy" in lines[1:]
        time.sleep(0.02)
    raise RuntimeError(f"FERNme key file {path} is empty; delete it or set {ENV_VAR}")


def _create_key_file(path: Path, key: bytes, legacy: bool) -> Tuple[bytes, bool]:
    """Publish the key file atomically: write a private temp file, then hard-link
    it into place (fails if another process won), so readers never see a
    half-written file."""
    tmp = path.with_name(f"{path.name}.{os.getpid()}.{secrets.token_hex(4)}.tmp")
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="ascii") as fh:
        fh.write(key.hex() + ("\naudit=legacy\n" if legacy else "\n"))
    try:
        os.link(str(tmp), str(path))
        return key, legacy
    except FileExistsError:
        return _read_key_file(path)
    finally:
        try:
            os.unlink(str(tmp))
        except OSError:
            pass


def resolve(store, explicit=None) -> Tuple[bytes, bool]:
    """Return ``(secret, audit_legacy)`` for this store.

    ``secret`` keys the private prior's noise (and new audit chains).
    ``audit_legacy`` means existing audit chains were signed with the legacy
    constant and must keep being verified with it."""
    secret, legacy, _source = resolve_detailed(store, explicit)
    return secret, legacy


def _from_text(value) -> bytes:
    raw = value.encode("utf-8") if isinstance(value, str) else bytes(value)
    if not raw:
        raise ValueError("secret_key must not be empty")
    return hashlib.sha256(raw).digest()


def resolve_detailed(store, explicit=None) -> Tuple[bytes, bool, str]:
    """Like :func:`resolve`, plus where the key came from: ``explicit``, ``env``,
    ``key_file``, ``database`` or ``ephemeral`` (a random key that does not
    survive a restart)."""
    if explicit is not None:
        return _from_text(explicit), False, "explicit"
    for name in ENV_ALIASES:
        env = os.environ.get(name)
        if env:
            return _from_text(env), False, "env"
    key_path = _key_path_for(store)
    if key_path is not None:
        if key_path.is_file():
            return (*_read_key_file(key_path), "key_file")
        try:
            return (*_create_key_file(key_path, secrets.token_bytes(32),
                                      _has_audit_rows(store)), "key_file")
        except OSError as exc:             # read-only folder, no hard links, ...
            print(f"FERNme: could not write key file ({exc}); "
                  f"set {ENV_VAR} for a stable key.", file=sys.stderr)
            return secrets.token_bytes(32), _has_audit_rows(store), "ephemeral"
    shared = getattr(store, "load_or_create_secret", None)
    if callable(shared):                     # e.g. Postgres: one secret per database
        key_hex, legacy = shared()
        return bytes.fromhex(key_hex), legacy, "database"
    return secrets.token_bytes(32), False, "ephemeral"


def derive(key: bytes, purpose: str) -> bytes:
    """Independent sub-key for a named purpose (e.g. prior noise)."""
    return hashlib.sha256(key + b"|" + purpose.encode("utf-8")).digest()
