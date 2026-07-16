"""Deterministic Obsidian vault parsing for the import service path.

Markdown text is preserved as Cabinet data. Wiki links and aliases become
human-reviewed suggestion candidates only; this module never mutates entity truth.
"""
from __future__ import annotations

import fnmatch
import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Sequence, Tuple

from ..curation_queue import SuggestionCandidate
from ..entity_kinds import ENTITY_KINDS, canonical_entity_kind
from ..safety import sanitize_tags
from ..vocabulary import Vocabulary
from .extractors import extract_structured


IMPORT_EVENT_TYPE = "obsidian_note"
IMPORTER_NAME = "obsidian"
_WIKILINK = re.compile(r"\[\[([^\]|#]+)(?:#[^\]|]+)?(?:\|([^\]]+))?\]\]")
_KEY = re.compile(r"[^a-z0-9]+")


@dataclass
class ObsidianNote:
    path: Path
    rel_path: str
    mtime: float
    title: str
    kind: str
    body: str
    frontmatter: Dict[str, object]
    tags: List[str]
    aliases: List[str]
    wikilinks: List[Tuple[str, str]]
    structured: List[Tuple[str, str]]
    import_id: str
    candidates: List[SuggestionCandidate] = field(default_factory=list)

    def payload(self) -> Dict:
        payload = {
            "tags": list(self.tags),
            "text": self.body,
            "source": "stated",
            "importer": IMPORTER_NAME,
            "import_id": self.import_id,
            "source_note": self.rel_path,
            "source_mtime": self.mtime,
            "content_redacted": False,
        }
        if self.structured:
            payload["structured"] = list(self.structured)
        if self.frontmatter:
            payload["frontmatter_keys"] = sorted(self.frontmatter)
        headings = _headings(self.body)
        if headings:
            payload["has_section"] = headings
        if self.wikilinks:
            payload["linked_note"] = [
                {"target": target, "label": label}
                for target, label in self.wikilinks
            ]
        return payload


def _slug(text: str, sep: str = "-") -> str:
    value = _KEY.sub(sep, str(text).lower()).strip(sep)
    return value or "untitled"


def _kind(value: object, title: str) -> str:
    kind = canonical_entity_kind(value)
    if kind != "other":
        return kind
    if value not in (None, ""):
        return "other"
    words = re.findall(r"[A-Z][a-z]+", title)
    if len(words) >= 2:
        return "person"
    return "other"


def _attr(kind: str, label: str, sep: str = "-") -> str:
    kind = canonical_entity_kind(kind)
    cleaned = sanitize_tags([f"{kind}:{_slug(label, sep)}"])
    return cleaned[0] if cleaned else f"{kind}:untitled"


def _display(label: str) -> str:
    return " ".join(part.capitalize() for part in re.findall(r"[a-z0-9]+", str(label).lower()))


def _as_list(value: object) -> List[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        raw = list(value)
    else:
        raw = [value]
    out: List[str] = []
    for item in raw:
        if item is None:
            continue
        text = str(item).strip().strip("\"'")
        if text:
            out.append(text)
    return out


def _parse_scalar(value: str) -> object:
    value = value.strip()
    if not value:
        return ""
    if value.startswith("[") and value.endswith("]"):
        inner = value[1:-1].strip()
        if not inner:
            return []
        return [part.strip().strip("\"'") for part in inner.split(",") if part.strip()]
    return value.strip("\"'")


def split_frontmatter(text: str) -> Tuple[Dict[str, object], str]:
    if not text.startswith("---"):
        return {}, text
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, text
    end = None
    for idx in range(1, len(lines)):
        if lines[idx].strip() == "---":
            end = idx
            break
    if end is None:
        return {}, text

    data: Dict[str, object] = {}
    idx = 1
    while idx < end:
        line = lines[idx]
        if not line.strip() or line.lstrip().startswith("#") or ":" not in line:
            idx += 1
            continue
        key, raw_value = line.split(":", 1)
        key = _slug(key, "_")
        raw_value = raw_value.strip()
        if raw_value:
            data[key] = _parse_scalar(raw_value)
            idx += 1
            continue
        values: List[str] = []
        idx += 1
        while idx < end and lines[idx].lstrip().startswith("-"):
            values.append(lines[idx].split("-", 1)[1].strip().strip("\"'"))
            idx += 1
        data[key] = values
    body = "\n".join(lines[end + 1:])
    if text.endswith("\n"):
        body += "\n"
    return data, body


def _frontmatter_tags(frontmatter: Dict[str, object], vocabulary: Vocabulary) -> List[str]:
    raw_tags: List[str] = []
    for item in _as_list(frontmatter.get("tags")):
        raw_tags.extend(part.strip() for part in item.split(",") if part.strip())
    for key, namespace in {
        "topic": "topic",
        "topics": "topic",
        "project": "project",
        "goal": "goal",
        "domain": "domain",
        "context": "context",
        "pref": "pref",
        "preference": "pref",
    }.items():
        for value in _as_list(frontmatter.get(key)):
            raw_tags.append(value if ":" in value else f"{namespace}:{_slug(value)}")
    out = []
    for tag in raw_tags:
        canonical = vocabulary.canonical(tag)
        if canonical and canonical not in out:
            out.append(canonical)
    return sanitize_tags(out)


def _headings(body: str) -> List[str]:
    out = []
    for line in body.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            heading = stripped.lstrip("#").strip()
            if heading:
                out.append(_slug(heading))
    return out[:16]


def _wikilinks(body: str) -> List[Tuple[str, str]]:
    out = []
    seen = set()
    for match in _WIKILINK.finditer(body):
        target = match.group(1).strip()
        label = (match.group(2) or target).strip()
        if not target:
            continue
        key = (target, label)
        if key not in seen:
            seen.add(key)
            out.append(key)
    return out


def _patterns(value: Sequence[str] | str | None) -> List[str]:
    if value is None:
        return []
    if isinstance(value, str):
        raw = [part.strip() for part in value.split(",")]
    else:
        raw = [str(part).strip() for part in value]
    return [part.replace("\\", "/") for part in raw if part]


def _matches(rel_path: str, patterns: Sequence[str]) -> bool:
    if not patterns:
        return False
    rel = rel_path.replace("\\", "/")
    for pattern in patterns:
        pat = pattern.strip("/")
        if fnmatch.fnmatch(rel, pat) or fnmatch.fnmatch(rel, f"{pat}/*") or rel.startswith(f"{pat}/"):
            return True
    return False


def _selected_markdown_files(
    vault: Path,
    include: Sequence[str] | str | None,
    exclude: Sequence[str] | str | None,
    max_notes: int | None,
) -> Tuple[List[Path], Dict[str, int]]:
    include_patterns = _patterns(include)
    exclude_patterns = _patterns(exclude)
    files = sorted(
        (p for p in vault.rglob("*.md") if p.is_file()),
        key=lambda p: p.relative_to(vault).as_posix().lower(),
    )
    selected: List[Path] = []
    skipped = {"include": 0, "exclude": 0, "cap": 0}
    for path in files:
        rel = path.relative_to(vault).as_posix()
        if include_patterns and not _matches(rel, include_patterns):
            skipped["include"] += 1
            continue
        if _matches(rel, exclude_patterns):
            skipped["exclude"] += 1
            continue
        if max_notes is not None and len(selected) >= int(max_notes):
            skipped["cap"] += 1
            continue
        selected.append(path)
    return selected, skipped


def _import_id(rel_path: str, mtime: float) -> str:
    raw = f"{rel_path}\0{mtime:.6f}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def _parse_note(path: Path, vault: Path, vocabulary: Vocabulary) -> ObsidianNote:
    text = path.read_text(encoding="utf-8")
    frontmatter, body = split_frontmatter(text)
    rel_path = path.relative_to(vault).as_posix()
    title = str(frontmatter.get("title") or path.stem).strip() or path.stem
    kind = _kind(frontmatter.get("kind") or frontmatter.get("type"), title)
    mtime = float(path.stat().st_mtime)
    tags = _frontmatter_tags(frontmatter, vocabulary)
    title_attr = _attr(kind, title)
    if kind != "other" and title_attr not in tags:
        tags.insert(0, title_attr)
    return ObsidianNote(
        path=path,
        rel_path=rel_path,
        mtime=mtime,
        title=title,
        kind=kind,
        body=body,
        frontmatter=frontmatter,
        tags=tags,
        aliases=_as_list(frontmatter.get("aliases") or frontmatter.get("alias")),
        wikilinks=_wikilinks(body),
        structured=extract_structured(body),
        import_id=_import_id(rel_path, mtime),
    )


def _link_target_key(target: str) -> str:
    return Path(target.replace("\\", "/")).stem.lower()


def _candidate(canonical: str, alias: str, kind: str, display_name: str,
               score: float = 0.88) -> SuggestionCandidate | None:
    canonical_clean = sanitize_tags([canonical])
    alias_clean = sanitize_tags([alias])
    if not canonical_clean or not alias_clean:
        return None
    canonical = canonical_clean[0]
    alias = alias_clean[0]
    if canonical == alias:
        return None
    return SuggestionCandidate(
        "alias-merge",
        {
            "canonical_attr": canonical,
            "alias_attr": alias,
            "entity_kind": kind if kind in ENTITY_KINDS else "other",
            "display_name": display_name,
            "source": "obsidian_import",
        },
        score,
    )


def _attach_candidates(notes: List[ObsidianNote]) -> None:
    by_title = {note.title.lower(): note for note in notes}
    by_stem = {Path(note.rel_path).stem.lower(): note for note in notes}
    for note in notes:
        canonical = _attr(note.kind, note.title)
        for alias in note.aliases:
            cand = _candidate(canonical, _attr(note.kind, alias, sep="_"),
                              note.kind, _display(note.title), score=0.90)
            if cand:
                note.candidates.append(cand)
        for target, label in note.wikilinks:
            target_note = by_title.get(target.lower()) or by_stem.get(_link_target_key(target))
            target_title = target_note.title if target_note else Path(target).stem
            target_kind = target_note.kind if target_note else _kind(None, target_title)
            target_canonical = _attr(target_kind, target_title)
            alias_label = label if label != target else target_title.replace(" ", "_")
            cand = _candidate(target_canonical, _attr(target_kind, alias_label, sep="_"),
                              target_kind, _display(target_title), score=0.86)
            if cand:
                note.candidates.append(cand)


def parse_vault(
    path: str | Path,
    include: Sequence[str] | str | None = None,
    exclude: Sequence[str] | str | None = None,
    max_notes: int | None = None,
    vocabulary: Vocabulary | None = None,
) -> Tuple[List[ObsidianNote], Dict[str, int]]:
    """Parse a vault into import-ready notes plus skipped counts.

    The returned notes contain raw body text, graph tags, structured fields, and
    review-only suggestion candidates. No writes happen here.
    """
    vault = Path(path).expanduser().resolve()
    if not vault.exists() or not vault.is_dir():
        raise ValueError("vault path must be an existing directory")
    if max_notes is not None and int(max_notes) < 0:
        raise ValueError("max_notes must be non-negative")
    vocab = vocabulary or Vocabulary(default_namespace="topic")
    files, skipped = _selected_markdown_files(vault, include, exclude, max_notes)
    notes = [_parse_note(path, vault, vocab) for path in files]
    _attach_candidates(notes)
    return notes, skipped


def imported_key(note: ObsidianNote) -> Tuple[str, float]:
    return (note.rel_path, note.mtime)


def imported_keys_from_events(events: Iterable[Dict]) -> set[Tuple[str, float]]:
    keys = set()
    for event in events:
        payload = event.get("payload", {})
        if payload.get("importer") != IMPORTER_NAME:
            continue
        source_note = payload.get("source_note")
        source_mtime = payload.get("source_mtime")
        if source_note is None or source_mtime is None:
            continue
        keys.add((str(source_note), float(source_mtime)))
    return keys
