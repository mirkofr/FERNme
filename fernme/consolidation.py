"""One-time canonicalization repair for fragmented historical tags.

Dry-run is the default. Applying requires an explicit DB path and a fresh
backup beside that DB. The tool never prints tag names; reports are aggregates
only so migration logs do not leak memory content.
"""
from __future__ import annotations

import argparse
import json
import math
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from .core.graph import Edge, UserGraph
from .store.sqlite_store import SQLiteStore
from .vocabulary import Vocabulary


META_SCHEMA = """
CREATE TABLE IF NOT EXISTS consolidation_runs(
  run_id TEXT PRIMARY KEY,
  created_at REAL NOT NULL,
  payload TEXT NOT NULL
);
"""

EDGE_COLUMNS = (
    "site", "user", "attr", "weight", "confidence", "source",
    "last_reinforced", "hits", "fast", "salience",
)
HISTORY_COLUMNS = ("site", "user", "attr", "ts")
ASSOC_COLUMNS = ("site", "a", "b", "weight")


class ConsolidationError(RuntimeError):
    pass


@dataclass(frozen=True)
class MergeGroup:
    site: str
    user: str
    canonical: str
    attrs: Tuple[str, ...]

    @property
    def variants(self) -> Tuple[str, ...]:
        return tuple(a for a in self.attrs if a != self.canonical)


@dataclass
class ConsolidationPlan:
    groups: List[MergeGroup] = field(default_factory=list)
    active_tags_before: int = 0
    existing_superseded: int = 0
    users_scanned: int = 0

    @property
    def active_tags_after(self) -> int:
        removed = sum(max(0, len(g.attrs) - 1) for g in self.groups)
        return self.active_tags_before - removed

    def report(self, *, run_id: Optional[str] = None, undone: bool = False) -> Dict:
        group_sizes = sorted((len(g.attrs) for g in self.groups), reverse=True)
        out = {
            "mode": "undo" if undone else ("apply" if run_id else "dry-run"),
            "users_scanned": self.users_scanned,
            "active_tags_before": self.active_tags_before,
            "active_tags_after": self.active_tags_after,
            "groups": len(self.groups),
            "variants_superseded": sum(len(g.variants) for g in self.groups),
            "sample_group_sizes": group_sizes[:10],
            "content_redacted": True,
        }
        if run_id:
            out["run_id"] = run_id
        return out


def _dicts(rows: Iterable) -> List[Dict]:
    return [dict(r) for r in rows]


def _edge_to_row(site: str, user: str, attr: str, edge: Edge) -> Tuple:
    return (
        site, user, attr, float(edge.weight), float(edge.confidence), edge.source,
        float(edge.last_reinforced), int(edge.hits), float(edge.fast),
        float(edge.salience),
    )


def _replace_user_graph(conn, ug: UserGraph) -> None:
    conn.execute("DELETE FROM user_edges WHERE site=? AND user=?", (ug.site, ug.user))
    conn.executemany(
        "INSERT INTO user_edges VALUES(?,?,?,?,?,?,?,?,?,?)",
        [_edge_to_row(ug.site, ug.user, attr, edge)
         for attr, edge in ug.edges.items()],
    )
    conn.execute("DELETE FROM user_history WHERE site=? AND user=?", (ug.site, ug.user))
    conn.executemany(
        "INSERT INTO user_history VALUES(?,?,?,?)",
        [(ug.site, ug.user, attr, ts)
         for attr, values in ug.history.items()
         for ts in values],
    )


def _active_edges(ug: UserGraph) -> Dict[str, Edge]:
    return {a: e for a, e in ug.edges.items() if e.source != "superseded"}


def _is_known_anchor(vocab: Vocabulary, canonical: Optional[str]) -> bool:
    return bool(canonical and canonical.lstrip("!") in vocab.terms)


def _site_users(store: SQLiteStore, site: Optional[str], user: Optional[str]) -> List[Tuple[str, str]]:
    query = "SELECT DISTINCT site,user FROM user_edges"
    clauses, args = [], []
    if site is not None:
        clauses.append("site=?")
        args.append(site)
    if user is not None:
        clauses.append("user=?")
        args.append(user)
    if clauses:
        query += " WHERE " + " AND ".join(clauses)
    query += " ORDER BY site,user"
    return [(r["site"], r["user"]) for r in store._conn.execute(query, args)]


def plan_consolidation(
    store: SQLiteStore,
    vocabulary: Vocabulary,
    *,
    site: Optional[str] = None,
    user: Optional[str] = None,
) -> ConsolidationPlan:
    """Build an aggregate-only plan. This function writes nothing."""
    plan = ConsolidationPlan()
    for s, u in _site_users(store, site, user):
        plan.users_scanned += 1
        ug = store.load_user(s, u)
        active = _active_edges(ug)
        plan.active_tags_before += len(active)
        plan.existing_superseded += sum(
            1 for edge in ug.edges.values() if edge.source == "superseded"
        )
        buckets: Dict[str, List[str]] = {}
        for attr in active:
            canonical, _alias = vocabulary.resolve(attr)
            if not _is_known_anchor(vocabulary, canonical):
                continue
            buckets.setdefault(canonical, []).append(attr)
        for canonical, attrs in sorted(buckets.items()):
            has_variant = any(attr != canonical for attr in attrs)
            if has_variant:
                ordered = tuple(sorted(attrs, key=lambda a: (a != canonical, a)))
                plan.groups.append(MergeGroup(s, u, canonical, ordered))
    return plan


def require_explicit_safe_db(db_path: str | Path) -> Path:
    path = Path(db_path)
    if not str(path):
        raise ConsolidationError("a target DB path is required")
    if path.name.lower() == "mirko.db":
        raise ConsolidationError("refusing to run on mirko.db")
    if not path.exists():
        raise ConsolidationError("target DB path does not exist")
    return path


def require_fresh_backup(db_path: str | Path, backup_path: str | Path) -> None:
    db = Path(db_path).resolve()
    backup = Path(backup_path).resolve()
    if not backup.exists():
        raise ConsolidationError("backup copy does not exist")
    if backup.parent != db.parent:
        raise ConsolidationError("backup copy must be alongside the target DB")
    if backup == db:
        raise ConsolidationError("backup copy must be a separate file")
    if backup.stat().st_mtime + 1e-6 < db.stat().st_mtime:
        raise ConsolidationError("backup copy is older than the target DB")


def _merge_edges(edges: Sequence[Edge]) -> Edge:
    hits = sum(int(e.hits) for e in edges)
    confidence = max((float(e.confidence) for e in edges), default=0.0)
    if hits:
        confidence = max(confidence, 1.0 - math.exp(-0.6 * hits))
    return Edge(
        weight=sum(float(e.weight) for e in edges),
        confidence=min(1.0, confidence),
        source="override" if any(e.source == "override" for e in edges) else "known",
        last_reinforced=max((float(e.last_reinforced) for e in edges), default=0.0),
        hits=hits,
        fast=sum(float(e.fast) for e in edges),
        salience=max((float(e.salience) for e in edges), default=0.0),
    )


def _snapshot(store: SQLiteStore, plan: ConsolidationPlan) -> Dict:
    conn = store._conn
    by_user: Dict[Tuple[str, str], set[str]] = {}
    by_site: set[str] = set()
    for group in plan.groups:
        key = (group.site, group.user)
        by_site.add(group.site)
        by_user.setdefault(key, set()).update(group.attrs)
        by_user[key].add(group.canonical)

    users = []
    for (site, user), attrs in sorted(by_user.items()):
        marks = ",".join("?" for _ in attrs)
        args = [site, user, *sorted(attrs)]
        users.append({
            "site": site,
            "user": user,
            "affected_attrs": sorted(attrs),
            "user_edges": _dicts(conn.execute(
                f"SELECT * FROM user_edges WHERE site=? AND user=? AND attr IN ({marks})",
                args,
            )),
            "user_history": _dicts(conn.execute(
                f"SELECT * FROM user_history WHERE site=? AND user=? AND attr IN ({marks})",
                args,
            )),
        })

    assoc = []
    for site in sorted(by_site):
        assoc.append({
            "site": site,
            "assoc_edges": _dicts(conn.execute(
                "SELECT * FROM assoc_edges WHERE site=?", (site,)
            )),
        })
    return {"version": 1, "users": users, "assoc": assoc}


def _apply_user_groups(store: SQLiteStore, groups: Sequence[MergeGroup]) -> None:
    by_user: Dict[Tuple[str, str], List[MergeGroup]] = {}
    for group in groups:
        by_user.setdefault((group.site, group.user), []).append(group)

    for (site, user), user_groups in by_user.items():
        ug = store.load_user(site, user)
        for group in user_groups:
            active_edges = [
                ug.edges[attr] for attr in group.attrs
                if attr in ug.edges and ug.edges[attr].source != "superseded"
            ]
            if not active_edges:
                continue
            ug.edges[group.canonical] = _merge_edges(active_edges)
            merged_history: List[float] = []
            for attr in group.attrs:
                merged_history.extend(ug.history.get(attr, []))
            ug.history[group.canonical] = sorted(merged_history)
            for variant in group.variants:
                if variant not in ug.edges:
                    continue
                old = ug.edges[variant]
                ug.edges[variant] = Edge(
                    weight=0.0,
                    confidence=old.confidence,
                    source="superseded",
                    last_reinforced=old.last_reinforced,
                    hits=old.hits,
                    fast=0.0,
                    salience=old.salience,
                )
        _replace_user_graph(store._conn, ug)


def _apply_assoc_groups(store: SQLiteStore, groups: Sequence[MergeGroup]) -> None:
    by_site: Dict[str, Dict[str, str]] = {}
    for group in groups:
        mapping = by_site.setdefault(group.site, {})
        for variant in group.variants:
            mapping[variant] = group.canonical

    for site, mapping in by_site.items():
        merged: Dict[Tuple[str, str], float] = {}
        for row in store._conn.execute(
            "SELECT a,b,weight FROM assoc_edges WHERE site=?", (site,)
        ):
            a = mapping.get(row["a"], row["a"])
            b = mapping.get(row["b"], row["b"])
            if a == b:
                continue
            key = (a, b) if a <= b else (b, a)
            merged[key] = merged.get(key, 0.0) + float(row["weight"])
        store._conn.execute("DELETE FROM assoc_edges WHERE site=?", (site,))
        store._conn.executemany(
            "INSERT INTO assoc_edges VALUES(?,?,?,?)",
            [(site, a, b, weight) for (a, b), weight in sorted(merged.items())],
        )


def apply_consolidation(
    db_path: str | Path,
    vocabulary: Vocabulary,
    *,
    backup_path: str | Path,
    site: Optional[str] = None,
    user: Optional[str] = None,
) -> Dict:
    db = require_explicit_safe_db(db_path)
    require_fresh_backup(db, backup_path)
    store = SQLiteStore(str(db))
    store._conn.executescript(META_SCHEMA)
    plan = plan_consolidation(store, vocabulary, site=site, user=user)
    if not plan.groups:
        return plan.report(run_id=None)

    run_id = str(uuid.uuid4())
    snapshot = _snapshot(store, plan)
    created_at = time.time()
    conn = store._conn
    conn.execute("BEGIN")
    try:
        _apply_user_groups(store, plan.groups)
        _apply_assoc_groups(store, plan.groups)
        conn.execute(
            "INSERT INTO consolidation_runs(run_id,created_at,payload) VALUES(?,?,?)",
            (run_id, created_at, json.dumps(snapshot, sort_keys=True)),
        )
        for site_user, user_groups in _groups_by_user(plan.groups).items():
            s, u = site_user
            payload = {
                "run_id": run_id,
                "groups": len(user_groups),
                "variants_superseded": sum(len(g.variants) for g in user_groups),
            }
            conn.execute(
                "INSERT INTO events(site,user,ts,type,payload,attrs) VALUES(?,?,?,?,?,?)",
                (s, u, created_at, "consolidation_alias",
                 json.dumps(payload, sort_keys=True), "[]"),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return plan.report(run_id=run_id)


def _groups_by_user(groups: Sequence[MergeGroup]) -> Dict[Tuple[str, str], List[MergeGroup]]:
    out: Dict[Tuple[str, str], List[MergeGroup]] = {}
    for group in groups:
        out.setdefault((group.site, group.user), []).append(group)
    return out


def undo_consolidation(db_path: str | Path, run_id: str) -> Dict:
    db = require_explicit_safe_db(db_path)
    store = SQLiteStore(str(db))
    store._conn.executescript(META_SCHEMA)
    row = store._conn.execute(
        "SELECT payload FROM consolidation_runs WHERE run_id=?", (run_id,)
    ).fetchone()
    if row is None:
        raise ConsolidationError("consolidation run was not found")
    snapshot = json.loads(row["payload"])
    conn = store._conn
    conn.execute("BEGIN")
    try:
        for user_snapshot in snapshot["users"]:
            site = user_snapshot["site"]
            user = user_snapshot["user"]
            attrs = user_snapshot["affected_attrs"]
            marks = ",".join("?" for _ in attrs)
            args = [site, user, *attrs]
            conn.execute(
                f"DELETE FROM user_edges WHERE site=? AND user=? AND attr IN ({marks})",
                args,
            )
            conn.execute(
                f"DELETE FROM user_history WHERE site=? AND user=? AND attr IN ({marks})",
                args,
            )
            conn.executemany(
                "INSERT INTO user_edges VALUES(?,?,?,?,?,?,?,?,?,?)",
                [tuple(r[c] for c in EDGE_COLUMNS) for r in user_snapshot["user_edges"]],
            )
            conn.executemany(
                "INSERT INTO user_history VALUES(?,?,?,?)",
                [tuple(r[c] for c in HISTORY_COLUMNS)
                 for r in user_snapshot["user_history"]],
            )
        for assoc_snapshot in snapshot["assoc"]:
            site = assoc_snapshot["site"]
            conn.execute("DELETE FROM assoc_edges WHERE site=?", (site,))
            conn.executemany(
                "INSERT INTO assoc_edges VALUES(?,?,?,?)",
                [tuple(r[c] for c in ASSOC_COLUMNS)
                 for r in assoc_snapshot["assoc_edges"]],
            )
        _delete_consolidation_events(conn, run_id)
        conn.execute("DELETE FROM consolidation_runs WHERE run_id=?", (run_id,))
        conn.commit()
    except Exception:
        conn.rollback()
        raise

    groups = sum(1 for _u in snapshot["users"])
    return {
        "mode": "undo",
        "users_restored": groups,
        "run_id": run_id,
        "content_redacted": True,
    }


def _delete_consolidation_events(conn, run_id: str) -> None:
    rows = list(conn.execute(
        "SELECT id,payload FROM events WHERE type='consolidation_alias'"
    ))
    for row in rows:
        try:
            payload = json.loads(row["payload"])
        except (TypeError, json.JSONDecodeError):
            continue
        if payload.get("run_id") == run_id:
            conn.execute("DELETE FROM events WHERE id=?", (row["id"],))


def dry_run(
    db_path: str | Path,
    vocabulary: Vocabulary,
    *,
    site: Optional[str] = None,
    user: Optional[str] = None,
) -> Dict:
    db = require_explicit_safe_db(db_path)
    store = SQLiteStore(str(db))
    return plan_consolidation(store, vocabulary, site=site, user=user).report()


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Consolidate historical tag aliases.")
    p.add_argument("--db", required=True, help="Explicit target SQLite DB path.")
    p.add_argument("--vocab", help="Vocabulary JSON path for dry-run/apply.")
    p.add_argument("--site", help="Optional site filter.")
    p.add_argument("--user", help="Optional user filter.")
    p.add_argument("--apply", action="store_true", help="Write the consolidation.")
    p.add_argument("--backup", help="Fresh backup copy beside --db; required for --apply.")
    p.add_argument("--undo", metavar="RUN_ID", help="Restore a previous run.")
    return p


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.undo:
            report = undo_consolidation(args.db, args.undo)
        else:
            if not args.vocab:
                raise ConsolidationError("--vocab is required for dry-run/apply")
            vocab = Vocabulary.from_json(args.vocab)
            if args.apply:
                if not args.backup:
                    raise ConsolidationError("--backup is required with --apply")
                report = apply_consolidation(
                    args.db, vocab, backup_path=args.backup,
                    site=args.site, user=args.user,
                )
            else:
                report = dry_run(args.db, vocab, site=args.site, user=args.user)
    except ConsolidationError as exc:
        print(json.dumps({"error": str(exc), "content_redacted": True}, sort_keys=True))
        return 2
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
