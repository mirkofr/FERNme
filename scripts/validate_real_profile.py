"""Validate an entity map against a copied FERNme SQLite profile.

This is engineer-hat tooling: it never modifies the input DB. The script first
copies the supplied DB into a temporary directory, applies any local entity map
there, then compares recall cards with entity flags off and on.
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
import tempfile
from dataclasses import replace
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fernme.config import DEFAULT
from fernme.retrieve.entity_card import card_token_estimate
from fernme.service import FernService
from fernme.store.sqlite_store import SQLiteStore


class ValidationError(RuntimeError):
    pass


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Validate a copied FERNme profile with a local entity map."
    )
    p.add_argument("--db", required=True, help="Path to a copied FERNme SQLite DB.")
    p.add_argument("--site", required=True, help="Site id to validate.")
    p.add_argument("--user", required=True, help="User id to validate.")
    p.add_argument(
        "--entity-map",
        help="Local *_entity_map.yaml file with entities, relations, and probes.",
    )
    p.add_argument(
        "--top-n",
        type=int,
        default=8,
        help="Card budget for off/on comparison and candidate cluster count.",
    )
    p.add_argument(
        "--interactive",
        action="store_true",
        help="Show candidate tag strings on this terminal. Default output is redacted.",
    )
    p.add_argument(
        "--i-am-the-owner-on-a-copy",
        action="store_true",
        help="Allow a copied DB whose filename starts with mirko.",
    )
    return p


def _require_safe_copy_path(path: str | Path, owner_flag: bool) -> Path:
    db = Path(path)
    if not db.exists():
        raise ValidationError("DB path does not exist")
    if not db.is_file():
        raise ValidationError("DB path is not a file")
    if db.name.lower().startswith("mirko") and not owner_flag:
        raise ValidationError(
            "refusing filenames matching mirko* without --i-am-the-owner-on-a-copy"
        )
    return db


def _copy_db_to_temp(db: Path, tmpdir: Path) -> Path:
    tmp_db = tmpdir / "profile_copy.db"
    src = sqlite3.connect(f"{db.resolve().as_uri()}?mode=ro", uri=True)
    dst = sqlite3.connect(str(tmp_db))
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    return tmp_db


def _load_spec(path: Optional[str | Path]) -> Dict[str, Any]:
    if path is None:
        return {"entities": [], "relations": [], "probes": []}
    text = Path(path).read_text(encoding="utf-8")
    if not text.strip():
        return {"entities": [], "relations": [], "probes": []}
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        try:
            import yaml  # type: ignore
        except ImportError:
            data = _parse_small_yaml(text)
        else:
            data = yaml.safe_load(text)
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise ValidationError("entity map must be a mapping")
    return {
        "entities": list(data.get("entities") or []),
        "relations": list(data.get("relations") or []),
        "probes": list(data.get("probes") or []),
    }


def _parse_scalar(value: str) -> Any:
    value = value.strip()
    if not value:
        return ""
    if value in {"[]", "{}"}:
        return [] if value == "[]" else {}
    if value[0:1] in {"'", '"'} and value[-1:] == value[0]:
        return value[1:-1]
    if value.lower() == "true":
        return True
    if value.lower() == "false":
        return False
    try:
        return int(value)
    except ValueError:
        try:
            return float(value)
        except ValueError:
            return value


def _parse_small_yaml(text: str) -> Dict[str, Any]:
    """Parse the tiny YAML subset documented for local entity maps.

    The fallback keeps the script dependency-free. It supports top-level lists of
    mappings, nested scalar lists, and one nested list of mappings for probe
    relation checks.
    """
    out: Dict[str, Any] = {}
    section: Optional[str] = None
    current: Optional[Dict[str, Any]] = None
    nested_key: Optional[str] = None
    nested_item: Optional[Dict[str, Any]] = None

    for raw in text.splitlines():
        line = raw.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip(" "))
        stripped = line.strip()
        if indent == 0 and stripped.endswith(":"):
            section = stripped[:-1]
            out[section] = []
            current = None
            nested_key = None
            nested_item = None
            continue
        if section is None:
            raise ValidationError("unsupported YAML: expected a top-level section")
        if indent == 2 and stripped.startswith("- "):
            current = {}
            out[section].append(current)
            nested_key = None
            nested_item = None
            rest = stripped[2:].strip()
            if rest:
                key, value = _split_key_value(rest)
                current[key] = _parse_scalar(value)
            continue
        if current is None:
            raise ValidationError("unsupported YAML: expected a list item")
        if indent == 4:
            key, value = _split_key_value(stripped)
            nested_item = None
            if value == "":
                current[key] = []
                nested_key = key
            else:
                current[key] = _parse_scalar(value)
                nested_key = None
            continue
        if indent == 6 and nested_key:
            rest = stripped
            if not rest.startswith("- "):
                key, value = _split_key_value(rest)
                if isinstance(current[nested_key], list) and not current[nested_key]:
                    current[nested_key] = {}
                if not isinstance(current[nested_key], dict):
                    raise ValidationError("unsupported YAML: mixed nested collection")
                current[nested_key][key] = _parse_scalar(value)
                continue
            rest = rest[2:].strip()
            if ":" in rest and nested_key in {"relations"}:
                key, value = _split_key_value(rest)
                nested_item = {key: _parse_scalar(value)}
                current[nested_key].append(nested_item)
            else:
                nested_item = None
                current[nested_key].append(_parse_scalar(rest))
            continue
        if indent == 8 and nested_item is not None:
            key, value = _split_key_value(stripped)
            nested_item[key] = _parse_scalar(value)
            continue
        raise ValidationError(f"unsupported YAML near: {stripped}")
    return out


def _split_key_value(text: str) -> Tuple[str, str]:
    if ":" not in text:
        raise ValidationError(f"unsupported YAML item: {text}")
    key, value = text.split(":", 1)
    return key.strip(), value.strip()


def _active_attrs(store: SQLiteStore, site: str, user: str) -> List[str]:
    rows = store._conn.execute(
        "SELECT attr FROM user_edges WHERE site=? AND user=? AND source!='superseded' "
        "ORDER BY attr",
        (site, user),
    )
    return [row["attr"] for row in rows]


def _tokens(attr: str) -> set[str]:
    value = attr[1:] if attr.startswith("!") else attr
    if ":" in value:
        value = value.split(":", 1)[1]
    return {part for part in re.split(r"[^a-z0-9]+", value.lower()) if part}


def _overlap(a: str, b: str) -> float:
    ta = _tokens(a)
    tb = _tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def _candidate_clusters(
    attrs: Sequence[str], top_n: int, interactive: bool
) -> List[Dict[str, Any]]:
    parent = {attr: attr for attr in attrs}
    pair_scores: Dict[Tuple[str, str], float] = {}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: str, b: str) -> None:
        ra = find(a)
        rb = find(b)
        if ra != rb:
            parent[rb] = ra

    for i, a in enumerate(attrs):
        for b in attrs[i + 1:]:
            score = _overlap(a, b)
            if score >= 0.5:
                pair_scores[(a, b)] = score
                union(a, b)

    grouped: Dict[str, List[str]] = {}
    for attr in attrs:
        grouped.setdefault(find(attr), []).append(attr)

    clusters = []
    for values in grouped.values():
        if len(values) < 2:
            continue
        scores = [
            pair_scores.get((a, b), pair_scores.get((b, a), _overlap(a, b)))
            for i, a in enumerate(values)
            for b in values[i + 1:]
        ]
        item: Dict[str, Any] = {
            "size": len(values),
            "score": round(max(scores or [0.0]), 3),
        }
        if interactive:
            item["attrs"] = sorted(values)
        clusters.append(item)
    clusters.sort(key=lambda row: (-row["score"], -row["size"]))
    return clusters[:top_n]


def fragmentation_report(
    store: SQLiteStore, site: str, user: str, top_n: int, interactive: bool
) -> Dict[str, Any]:
    attrs = _active_attrs(store, site, user)
    clusters = _candidate_clusters(attrs, top_n, interactive)
    return {
        "tag_count": len(attrs),
        "candidate_alias_clusters": [
            {"cluster_index": i + 1, **cluster}
            for i, cluster in enumerate(clusters)
        ],
        "content_redacted": not interactive,
    }


def _coerce_str_list(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [str(v) for v in value]
    raise ValidationError("expected a string or list of strings")


def apply_entity_map(svc: FernService, site: str, user: str, spec: Dict[str, Any]) -> Dict[str, Any]:
    local_to_entity: Dict[str, str] = {}
    aliases_by_local: Dict[str, List[str]] = {}

    for index, entity in enumerate(spec["entities"]):
        if not isinstance(entity, dict):
            raise ValidationError("each entity must be a mapping")
        local_id = str(entity.get("id") or f"entity_{index + 1}")
        kind = str(entity["kind"])
        display_name = str(entity["display_name"])
        entity_id = svc.entity_create(site, user, kind, display_name)
        local_to_entity[local_id] = entity_id
        aliases = _coerce_str_list(entity.get("aliases"))
        aliases_by_local[local_id] = aliases
        for alias in aliases:
            svc.entity_link_alias(site, user, entity_id, alias)
        fields = entity.get("fields") or {}
        if not isinstance(fields, dict):
            raise ValidationError("entity fields must be a mapping")
        for field, value in sorted(fields.items()):
            svc.entity_set_field(site, user, entity_id, str(field), str(value))

    for relation in spec["relations"]:
        if not isinstance(relation, dict):
            raise ValidationError("each relation must be a mapping")
        subject = local_to_entity[str(relation["subject"])]
        obj = local_to_entity[str(relation["object"])]
        svc.entity_relate(
            site,
            user,
            subject,
            str(relation["relation"]),
            obj,
            note=str(relation.get("note") or ""),
            provenance=str(relation.get("provenance") or "stated"),
            ts=float(relation.get("ts") or 0.0),
        )

    return {"entity_ids": local_to_entity, "aliases_by_local": aliases_by_local}


def _rank(card: Dict[str, Any], aliases: Sequence[str]) -> Optional[int]:
    attrs = [row["attr"] for row in card.get("links", [])]
    ranks = [attrs.index(alias) + 1 for alias in aliases if alias in attrs]
    return min(ranks) if ranks else None


def _relation_visible(card: Dict[str, Any], relation: Dict[str, Any]) -> bool:
    return str(relation.get("relation", "")) in str(card.get("wire", ""))


def _target_aliases(target: str, aliases_by_local: Dict[str, List[str]]) -> List[str]:
    return aliases_by_local.get(target) or [target]


def _close_service(svc: FernService) -> None:
    try:
        svc.store._conn.close()
    except Exception:
        pass


def run_probe_report(
    db_path: Path,
    site: str,
    user: str,
    spec: Dict[str, Any],
    map_meta: Dict[str, Any],
    top_n: int,
) -> List[Dict[str, Any]]:
    off_svc = FernService(
        str(db_path),
        cfg=replace(DEFAULT, top_n=top_n, entities=False, entity_aggregation=False),
    )
    on_svc = FernService(
        str(db_path),
        cfg=replace(DEFAULT, top_n=top_n, entities=True, entity_aggregation=True),
    )
    aliases_by_local = map_meta["aliases_by_local"]
    try:
        out = []
        for probe_index, probe in enumerate(spec["probes"]):
            if not isinstance(probe, dict):
                raise ValidationError("each probe must be a mapping")
            probe_id = str(probe.get("id") or f"probe_{probe_index + 1}")
            context = _coerce_str_list(probe.get("context"))
            off_card = off_svc.card(site, user, context=context)
            on_card = on_svc.card(site, user, context=context)
            targets = []
            for target_index, target in enumerate(_coerce_str_list(probe.get("targets"))):
                aliases = _target_aliases(str(target), aliases_by_local)
                targets.append({
                    "target_index": target_index + 1,
                    "rank_off": _rank(off_card, aliases),
                    "rank_on": _rank(on_card, aliases),
                })
            relation_checks = []
            for relation_index, relation in enumerate(probe.get("relations") or []):
                if not isinstance(relation, dict):
                    raise ValidationError("probe relations must be mappings")
                relation_checks.append({
                    "relation_index": relation_index + 1,
                    "appears_off": _relation_visible(off_card, relation),
                    "appears_on": _relation_visible(on_card, relation),
                })
            out.append({
                "probe_id": probe_id,
                "token_estimate_off": card_token_estimate(off_card["wire"]),
                "token_estimate_on": card_token_estimate(on_card["wire"]),
                "targets": targets,
                "relation_checks": relation_checks,
            })
        return out
    finally:
        _close_service(off_svc)
        _close_service(on_svc)


def validate_profile(
    db_path: str | Path,
    site: str,
    user: str,
    entity_map: Optional[str | Path],
    *,
    top_n: int = 8,
    interactive: bool = False,
    owner_flag: bool = False,
) -> Dict[str, Any]:
    source_db = _require_safe_copy_path(db_path, owner_flag)
    spec = _load_spec(entity_map)
    with tempfile.TemporaryDirectory(prefix="fernme-profile-validate-") as tmp:
        tmp_db = _copy_db_to_temp(source_db, Path(tmp))
        store = SQLiteStore(str(tmp_db))
        svc = None
        try:
            if not store.has_consent(site, user):
                raise ValidationError("site/user has no consent in the copied DB")
            before = fragmentation_report(store, site, user, top_n, interactive)
            svc = FernService(str(tmp_db), cfg=replace(DEFAULT, top_n=top_n))
            map_meta = apply_entity_map(svc, site, user, spec)
            _close_service(svc)
            svc = None
            probes = run_probe_report(tmp_db, site, user, spec, map_meta, top_n)
        finally:
            store._conn.close()
            if svc is not None:
                _close_service(svc)
    return {
        "mode": "validate-real-profile",
        "input_modified": False,
        "worked_on_temp_copy": True,
        "site_user": {"site": site, "user": user},
        "fragmentation": before,
        "entity_map": {
            "entities": len(spec["entities"]),
            "relations": len(spec["relations"]),
            "probes": len(spec["probes"]),
        },
        "probes": probes,
        "content_redacted": not interactive,
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _parser().parse_args(argv)
    try:
        report = validate_profile(
            args.db,
            args.site,
            args.user,
            args.entity_map,
            top_n=args.top_n,
            interactive=args.interactive,
            owner_flag=args.i_am_the_owner_on_a_copy,
        )
    except (KeyError, ValueError, ValidationError) as exc:
        print(json.dumps({"error": str(exc), "content_redacted": True}, sort_keys=True))
        return 2
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
