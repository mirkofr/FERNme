"""Safe managed-vault storage helpers for durable document evidence."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import re
import tempfile
import unicodedata


DOCUMENTS_DIR = "documents"


class DocumentStorageError(ValueError):
    """A managed document path or write could not be handled safely."""


@dataclass(frozen=True)
class DocumentPaths:
    markdown_path: str
    envelope_path: str


def vault_root_for_store(store, explicit: str | os.PathLike | None = None):
    """Return the configured vault root without creating it."""
    selected = explicit or os.environ.get("FERNME_VAULT")
    if selected:
        return Path(selected).expanduser().resolve()
    db_path = getattr(store, "path", None)
    if not db_path or db_path == ":memory:":
        return None
    return Path(db_path).expanduser().resolve().parent


def owner_key(site: str, user: str) -> str:
    raw = (str(site) + "\0" + str(user)).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:24]


def safe_source_stem(source_name: str) -> str:
    """Create a bounded ASCII filename stem from untrusted display text."""
    raw = str(source_name or "document").replace("\\", "/").split("/")[-1]
    stem = raw
    if stem.lower().endswith(".fernmark.json"):
        stem = stem[:-len(".fernmark.json")]
    else:
        stem = Path(stem).stem
    stem = unicodedata.normalize("NFKD", stem).encode("ascii", "ignore").decode("ascii")
    stem = re.sub(r"[^A-Za-z0-9._-]+", "-", stem).strip(" .-_")
    return (stem or "document")[:80]


def _inside(root: Path, candidate: Path) -> bool:
    try:
        return os.path.commonpath((str(root), str(candidate))) == str(root)
    except ValueError:
        return False


def _managed_target(vault_root: Path, relative_path: str,
                    strict: bool = False) -> Path:
    """Resolve a vault-relative pointer, always enforcing containment first.

    The containment check uses a non-strict (lexical) resolve so it cannot be
    bypassed just because an intermediate directory happens not to exist yet
    (e.g. a vault that was never created). Only after containment is proven do
    we optionally require the target to actually exist on disk, and that
    existence check raises a plain ``FileNotFoundError`` -- never the same
    exception type used for an invalid/hostile pointer -- so callers cannot
    conflate "safe pointer, nothing there yet" with "unsafe pointer".
    """
    relative = Path(str(relative_path))
    if relative.is_absolute() or not relative.parts or relative.parts[0] != DOCUMENTS_DIR:
        raise DocumentStorageError("document pointer must stay inside the managed vault")
    if any(part in ("", ".", "..") for part in relative.parts):
        raise DocumentStorageError("document pointer must stay inside the managed vault")
    root = vault_root.resolve()
    try:
        target = (root / relative).resolve(strict=False)
    except (OSError, RuntimeError, ValueError) as exc:
        raise DocumentStorageError(
            "document pointer must stay inside the managed vault") from exc
    if not _inside(root, target):
        raise DocumentStorageError("document pointer must stay inside the managed vault")
    if strict and not target.exists():
        raise FileNotFoundError(str(target))
    return target


def _matches(path: Path, text: str) -> bool:
    try:
        return path.is_file() and path.read_text(encoding="utf-8") == text
    except (OSError, UnicodeError):
        return False


def plan_document_paths(vault_root: Path, site: str, user: str,
                        source_name: str, source_sha256: str,
                        markdown: str, envelope: str) -> DocumentPaths:
    """Plan deterministic vault-relative paths without writing anything."""
    root = Path(vault_root).resolve()
    folder = Path(DOCUMENTS_DIR) / owner_key(site, user)
    stem = safe_source_stem(source_name)

    def paths(name: str) -> DocumentPaths:
        return DocumentPaths(
            (folder / (name + ".md")).as_posix(),
            (folder / (name + ".fernmark.json")).as_posix(),
        )

    base = paths(stem)
    base_md = _managed_target(root, base.markdown_path)
    base_env = _managed_target(root, base.envelope_path)
    occupied = base_md.exists() or base_env.exists()
    if not occupied or (_matches(base_md, markdown) and _matches(base_env, envelope)):
        return base

    hashed = paths(stem + "--" + str(source_sha256)[:12])
    hashed_md = _managed_target(root, hashed.markdown_path)
    hashed_env = _managed_target(root, hashed.envelope_path)
    if ((hashed_md.exists() and not _matches(hashed_md, markdown)) or
            (hashed_env.exists() and not _matches(hashed_env, envelope))):
        raise DocumentStorageError("managed document filename collision")
    return hashed


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_name = None
    try:
        with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", newline="\n",
                dir=str(path.parent), prefix=".fernme-", suffix=".tmp",
                delete=False) as handle:
            temp_name = handle.name
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
        temp_name = None
    except (OSError, UnicodeError) as exc:
        raise DocumentStorageError("could not write managed document files") from exc
    finally:
        if temp_name:
            try:
                Path(temp_name).unlink(missing_ok=True)
            except OSError:
                pass


def persist_document_files(vault_root: Path, paths: DocumentPaths,
                           markdown: str, envelope: str) -> list[str]:
    """Atomically write missing files and return only newly created pointers."""
    root = Path(vault_root).resolve()
    targets = (
        (paths.markdown_path, markdown),
        (paths.envelope_path, envelope),
    )
    created = []
    try:
        for relative, text in targets:
            target = _managed_target(root, relative)
            if target.exists():
                if not _matches(target, text):
                    raise DocumentStorageError("managed document filename collision")
                continue
            _atomic_write_text(target, text)
            created.append(relative)
    except Exception:
        delete_managed_files(root, created)
        raise
    return created


def read_managed_text(vault_root: Path, relative_path: str,
                      max_bytes: int = 64 * 1024 * 1024) -> str:
    """Safely read a managed vault text file by its vault-relative pointer.

    Enforces the same containment rules as every other vault operation and
    bounds the amount of raw bytes considered before decoding, independent of
    any caller-side pagination cap.
    """
    target = _managed_target(Path(vault_root), str(relative_path), strict=True)
    if not target.is_file():
        raise DocumentStorageError("managed document pointer is not a regular file")
    try:
        if target.stat().st_size > max_bytes:
            raise DocumentStorageError(
                "managed document exceeds the configured read size limit")
        return target.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise DocumentStorageError("could not read managed document text") from exc


def delete_managed_files(vault_root: Path, relative_paths) -> int:
    """Delete only regular, non-symlink files below the managed documents root."""
    root = Path(vault_root).resolve()
    deleted = 0
    for relative in list(relative_paths or []):
        if not relative:                      # e.g. a legacy backfilled row
            continue                          # with no vault artifact at all
        candidate = root / Path(str(relative))
        if candidate.is_symlink():
            raise DocumentStorageError("refusing to delete a managed document symlink")
        try:
            target = _managed_target(root, str(relative), strict=True)
        except FileNotFoundError:
            continue
        if not target.is_file():
            raise DocumentStorageError("managed document pointer is not a regular file")
        target.unlink()
        deleted += 1
        parent = target.parent
        documents_root = root / DOCUMENTS_DIR
        while parent != documents_root and _inside(documents_root, parent):
            try:
                parent.rmdir()
            except OSError:
                break
            parent = parent.parent
    return deleted


__all__ = [
    "DOCUMENTS_DIR",
    "DocumentPaths",
    "DocumentStorageError",
    "delete_managed_files",
    "owner_key",
    "persist_document_files",
    "plan_document_paths",
    "read_managed_text",
    "safe_source_stem",
    "vault_root_for_store",
]
