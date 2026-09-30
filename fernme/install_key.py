"""Per-install secret for the audit chain and the private prior's noise.

The audit chain used to be keyed with a constant that is public in the source,
so anyone with database access could rewrite history and still pass
``verify_audit``. The key now comes from, in order:

1. ``FERNME_SECRET_KEY`` (any string; set the same value on every process that
   shares a database, e.g. a Postgres deployment);
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


def resolve(store) -> Tuple[bytes, bool]:
    """Return ``(secret, audit_legacy)`` for this store.

    ``secret`` keys the private prior's noise (and new audit chains).
    ``audit_legacy`` means existing audit chains were signed with the legacy
    constant and must keep being verified with it."""
    env = os.environ.get(ENV_VAR)
    if env:
        return hashlib.sha256(env.encode("utf-8")).digest(), False
    key_path = _key_path_for(store)
    if key_path is not None:
        if key_path.is_file():
            return _read_key_file(key_path)
        try:
            return _create_key_file(key_path, secrets.token_bytes(32),
                                    _has_audit_rows(store))
        except OSError as exc:             # read-only folder, no hard links, ...
            print(f"FERNme: could not write key file ({exc}); "
                  f"set {ENV_VAR} for a stable key.", file=sys.stderr)
            return secrets.token_bytes(32), _has_audit_rows(store)
    shared = getattr(store, "load_or_create_secret", None)
    if callable(shared):                     # e.g. Postgres: one secret per database
        key_hex, legacy = shared()
        return bytes.fromhex(key_hex), legacy
    return secrets.token_bytes(32), False


def derive(key: bytes, purpose: str) -> bytes:
    """Independent sub-key for a named purpose (e.g. prior noise)."""
    return hashlib.sha256(key + b"|" + purpose.encode("utf-8")).digest()
