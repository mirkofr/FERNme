"""SQLite-backed multi-tenant store for FERN v1. One file, no server.
Swap to Postgres later behind this same interface. Isolation is enforced by
(site, user) on every query."""
from __future__ import annotations
import sqlite3, json, threading, os
from ..audit import entry_hash, GENESIS
from typing import List, Optional, Dict
from ..core.graph import UserGraph, AssocGraph, Edge, Event
from ..prior.population import PopulationPrior

SCHEMA = """
CREATE TABLE IF NOT EXISTS consents(
  site TEXT, user TEXT, granted INTEGER, ts REAL,
  PRIMARY KEY(site, user));
CREATE TABLE IF NOT EXISTS user_edges(
  site TEXT, user TEXT, attr TEXT, weight REAL, confidence REAL,
  source TEXT, last_reinforced REAL, hits INTEGER, fast REAL DEFAULT 0, salience REAL DEFAULT 0,
  provenance TEXT NOT NULL DEFAULT 'inferred',
  PRIMARY KEY(site, user, attr));
CREATE TABLE IF NOT EXISTS user_numeric(
  site TEXT, user TEXT, key TEXT, value TEXT,
  PRIMARY KEY(site, user, key));
CREATE TABLE IF NOT EXISTS user_history(
  site TEXT, user TEXT, attr TEXT, ts REAL);
CREATE TABLE IF NOT EXISTS assoc_edges(
  site TEXT, a TEXT, b TEXT, weight REAL, users INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY(site, a, b));
CREATE TABLE IF NOT EXISTS assoc_edge_users(
  site TEXT NOT NULL, user TEXT NOT NULL, a TEXT NOT NULL, b TEXT NOT NULL,
  hits INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY(site, user, a, b));
CREATE TABLE IF NOT EXISTS events(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  site TEXT, user TEXT, ts REAL, type TEXT, payload TEXT, attrs TEXT);
CREATE TABLE IF NOT EXISTS prior_node(
  site TEXT, attr TEXT, sum REAL, n INTEGER,
  PRIMARY KEY(site, attr));
CREATE TABLE IF NOT EXISTS prior_meta(
  site TEXT PRIMARY KEY, n_users INTEGER);
CREATE TABLE IF NOT EXISTS identities(
  person TEXT, site TEXT, local_user TEXT, ts REAL,
  PRIMARY KEY(person, site, local_user));
CREATE TABLE IF NOT EXISTS share_policy(
  person TEXT, target_site TEXT, category TEXT, allowed INTEGER,
  PRIMARY KEY(person, target_site, category));
CREATE TABLE IF NOT EXISTS entities(
  entity_id TEXT PRIMARY KEY, site TEXT NOT NULL, user TEXT NOT NULL,
  kind TEXT NOT NULL, display_name TEXT NOT NULL, created_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS entity_aliases(
  site TEXT NOT NULL, user TEXT NOT NULL, alias_attr TEXT NOT NULL,
  entity_id TEXT NOT NULL, source TEXT NOT NULL DEFAULT 'stated',
  confidence REAL NOT NULL DEFAULT 1.0,
  PRIMARY KEY(site, user, alias_attr));
CREATE TABLE IF NOT EXISTS entity_fields(
  entity_id TEXT NOT NULL, field TEXT NOT NULL,
  value TEXT NOT NULL, provenance TEXT NOT NULL DEFAULT 'stated', ts REAL NOT NULL,
  PRIMARY KEY(entity_id, field));
CREATE TABLE IF NOT EXISTS entity_relations(
  site TEXT NOT NULL, user TEXT NOT NULL,
  subject_id TEXT NOT NULL, relation TEXT NOT NULL, object_id TEXT NOT NULL,
  weight REAL NOT NULL DEFAULT 0.0, confidence REAL NOT NULL DEFAULT 0.0,
  hits INTEGER NOT NULL DEFAULT 0, last_reinforced REAL NOT NULL DEFAULT 0.0,
  salience REAL NOT NULL DEFAULT 0.0, provenance TEXT NOT NULL DEFAULT 'stated',
  note TEXT NOT NULL DEFAULT '',
  PRIMARY KEY(site, user, subject_id, relation, object_id));
CREATE TABLE IF NOT EXISTS relation_facts(
  fact_id TEXT PRIMARY KEY,
  site TEXT NOT NULL, user TEXT NOT NULL,
  subject_id TEXT NOT NULL, relation TEXT NOT NULL, object_id TEXT NOT NULL,
  note TEXT NOT NULL DEFAULT '',
  ts REAL NOT NULL,
  provenance TEXT NOT NULL DEFAULT 'stated',
  event_id INTEGER,
  UNIQUE(site, user, subject_id, relation, object_id, note),
  FOREIGN KEY(site, user, subject_id, relation, object_id)
    REFERENCES entity_relations(site, user, subject_id, relation, object_id)
    ON DELETE CASCADE);
CREATE TABLE IF NOT EXISTS canonicalization_suggestions(
  suggestion_id TEXT PRIMARY KEY,
  site TEXT NOT NULL, user TEXT NOT NULL,
  kind TEXT NOT NULL, payload TEXT NOT NULL, score REAL NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending',
  created_ts REAL NOT NULL, decided_ts REAL);
CREATE TABLE IF NOT EXISTS documents(
  document_id TEXT PRIMARY KEY, site TEXT NOT NULL, user TEXT NOT NULL,
  source_sha256 TEXT NOT NULL, source_name TEXT NOT NULL,
  markdown_path TEXT NOT NULL, envelope_path TEXT NOT NULL,
  mime_type TEXT NOT NULL, extraction_quality TEXT NOT NULL,
  warning_count INTEGER NOT NULL, block_count INTEGER NOT NULL,
  created_ts REAL NOT NULL, imported_ts REAL NOT NULL,
  status TEXT NOT NULL DEFAULT 'active', pinned INTEGER NOT NULL DEFAULT 0,
  authoritative INTEGER NOT NULL DEFAULT 0, superseded_by TEXT NOT NULL DEFAULT '',
  UNIQUE(site, user, source_sha256));
CREATE TABLE IF NOT EXISTS document_tags(
  document_id TEXT NOT NULL, site TEXT NOT NULL, user TEXT NOT NULL,
  tag TEXT NOT NULL, provenance TEXT NOT NULL DEFAULT 'human_approved',
  suggestion_id TEXT NOT NULL DEFAULT '', approved_ts REAL NOT NULL,
  PRIMARY KEY(document_id, tag));
CREATE TABLE IF NOT EXISTS assets(
  id TEXT PRIMARY KEY, site TEXT NOT NULL, user TEXT NOT NULL,
  type TEXT NOT NULL, mime TEXT NOT NULL, uri TEXT NOT NULL,
  sha256 TEXT NOT NULL, bytes INTEGER NOT NULL, created_ts REAL NOT NULL,
  source TEXT NOT NULL, thumbnail_uri TEXT NOT NULL,
  exif_stripped INTEGER NOT NULL, sensitive INTEGER NOT NULL,
  consent INTEGER NOT NULL, status TEXT NOT NULL DEFAULT 'active');
CREATE TABLE IF NOT EXISTS audit(
  site TEXT, user TEXT, seq INTEGER, ts REAL, action TEXT, detail TEXT,
  prev_hash TEXT, hash TEXT, PRIMARY KEY(site, user, seq));
CREATE INDEX IF NOT EXISTS idx_events_user ON events(site, user, ts);
CREATE INDEX IF NOT EXISTS idx_hist_user ON user_history(site, user, attr);
CREATE INDEX IF NOT EXISTS idx_assoc_edge_users_edge
  ON assoc_edge_users(site, a, b);
CREATE INDEX IF NOT EXISTS idx_relation_facts_relation
  ON relation_facts(site, user, subject_id, relation, object_id, ts);
CREATE INDEX IF NOT EXISTS idx_canonicalization_suggestions_user
  ON canonicalization_suggestions(site, user, status, created_ts);
CREATE INDEX IF NOT EXISTS idx_documents_owner_status
  ON documents(site, user, status, pinned, imported_ts);
CREATE INDEX IF NOT EXISTS idx_document_tags_owner_tag
  ON document_tags(site, user, tag, document_id);
CREATE INDEX IF NOT EXISTS idx_assets_owner_status
  ON assets(site, user, status, created_ts);
CREATE UNIQUE INDEX IF NOT EXISTS idx_assets_owner_sha_active
  ON assets(site, user, sha256) WHERE status='active';
"""


class SQLiteStore:
    def __init__(self, path: str = "fernme.db"):
        self.path = path
        d = os.path.dirname(os.path.abspath(path))
        os.makedirs(d, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(path, check_same_thread=False, timeout=30.0)
        self._conn.row_factory = sqlite3.Row
        try:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA busy_timeout=30000")
        except sqlite3.OperationalError:
            pass
        self._conn.executescript(SCHEMA)
        self._migrate()
        self._conn.commit()

    def _migrate(self):
        """Add columns introduced after a DB was first created (CREATE TABLE IF NOT
        EXISTS never alters an existing table). Keeps old DBs forward-compatible."""
        cols = {r[1] for r in self._conn.execute("PRAGMA table_info(user_edges)")}
        for col in ("fast", "salience"):
            if col not in cols:
                self._conn.execute("ALTER TABLE user_edges ADD COLUMN %s REAL DEFAULT 0" % col)
        if "provenance" not in cols:
            self._conn.execute(
                "ALTER TABLE user_edges ADD COLUMN provenance TEXT NOT NULL DEFAULT 'inferred'"
            )
        assoc_cols = {r[1] for r in self._conn.execute("PRAGMA table_info(assoc_edges)")}
        if "users" not in assoc_cols:
            self._conn.execute(
                "ALTER TABLE assoc_edges ADD COLUMN users INTEGER NOT NULL DEFAULT 0"
            )
        self._backfill_assoc_contributors()

    @staticmethod
    def _assoc_key(a: str, b: str):
        return (a, b) if a <= b else (b, a)

    @staticmethod
    def _pairs_from_attrs(attrs):
        names = []
        for item in attrs:
            if not item:
                continue
            if isinstance(item, (list, tuple)):
                names.append(str(item[0]))
            else:
                names.append(str(item))
        out = []
        for i in range(len(names)):
            for j in range(i + 1, len(names)):
                out.append(SQLiteStore._assoc_key(names[i], names[j]))
        return out

    def _refresh_assoc_user_counts(self, site: str, pairs=None, delete_empty: bool = False):
        pairs = list(dict.fromkeys(pairs or []))
        if not pairs:
            return
        for a, b in pairs:
            count = self._conn.execute(
                "SELECT COUNT(*) n FROM assoc_edge_users WHERE site=? AND a=? AND b=?",
                (site, a, b)).fetchone()["n"]
            if delete_empty and count == 0:
                self._conn.execute(
                    "DELETE FROM assoc_edges WHERE site=? AND a=? AND b=?",
                    (site, a, b))
            else:
                self._conn.execute(
                    "UPDATE assoc_edges SET users=? WHERE site=? AND a=? AND b=?",
                    (int(count), site, a, b))

    def _backfill_assoc_contributors(self):
        existing = self._conn.execute(
            "SELECT COUNT(*) n FROM assoc_edge_users").fetchone()["n"]
        if existing:
            return
        pairs_by_site = {}
        for r in self._conn.execute("SELECT site,user,attrs FROM events"):
            try:
                attrs = json.loads(r["attrs"])
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
            pairs = self._pairs_from_attrs(attrs)
            for a, b in pairs:
                pairs_by_site.setdefault(r["site"], set()).add((a, b))
                self._conn.execute(
                    "INSERT INTO assoc_edge_users(site,user,a,b,hits) VALUES(?,?,?,?,1) "
                    "ON CONFLICT(site,user,a,b) DO UPDATE SET hits=hits+1",
                    (r["site"], r["user"], a, b))
        for site, pairs in pairs_by_site.items():
            self._refresh_assoc_user_counts(site, pairs)

    # ---- consent ----
    def set_consent(self, site: str, user: str, granted: bool, ts: float = 0.0):
        with self._lock:
            self._conn.execute(
                "INSERT INTO consents(site,user,granted,ts) VALUES(?,?,?,?) "
                "ON CONFLICT(site,user) DO UPDATE SET granted=excluded.granted, ts=excluded.ts",
                (site, user, int(granted), ts))
            self._conn.commit()

    def has_consent(self, site: str, user: str) -> bool:
        r = self._conn.execute(
            "SELECT granted FROM consents WHERE site=? AND user=?", (site, user)).fetchone()
        return bool(r["granted"]) if r else False

    def list_consented_contexts(self, limit: int = 20):
        return [dict(r) for r in self._conn.execute(
            "SELECT site,user FROM consents WHERE granted=1 ORDER BY ts DESC, site, user LIMIT ?",
            (int(limit),))]

    # ---- user graph ----
    def load_user(self, site: str, user: str) -> UserGraph:
        ug = UserGraph(site, user)
        for r in self._conn.execute(
                "SELECT * FROM user_edges WHERE site=? AND user=?", (site, user)):
            ug.edges[r["attr"]] = Edge(r["weight"], r["confidence"], r["source"],
                                       r["last_reinforced"], r["hits"],
                                       r["fast"] if "fast" in r.keys() else 0.0,
                                       r["salience"] if "salience" in r.keys() else 0.0,
                                       r["provenance"] if "provenance" in r.keys() else "inferred")
        for r in self._conn.execute(
                "SELECT key,value FROM user_numeric WHERE site=? AND user=?", (site, user)):
            v = r["value"]
            try:
                v = float(v)
                if v.is_integer():
                    v = int(v)
            except (ValueError, TypeError):
                pass
            ug.numeric[r["key"]] = v
        for r in self._conn.execute(
                "SELECT attr,ts FROM user_history WHERE site=? AND user=?", (site, user)):
            ug.history.setdefault(r["attr"], []).append(r["ts"])
        return ug

    def save_user(self, ug: UserGraph):
        with self._lock:
            c = self._conn
            c.execute("DELETE FROM user_edges WHERE site=? AND user=?", (ug.site, ug.user))
            c.executemany(
                "INSERT INTO user_edges VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                [(ug.site, ug.user, a, e.weight, e.confidence, e.source,
                  e.last_reinforced, e.hits, e.fast, e.salience, e.provenance)
                 for a, e in ug.edges.items()])
            c.execute("DELETE FROM user_numeric WHERE site=? AND user=?", (ug.site, ug.user))
            c.executemany("INSERT INTO user_numeric VALUES(?,?,?,?)",
                          [(ug.site, ug.user, k, str(v)) for k, v in ug.numeric.items()])
            c.execute("DELETE FROM user_history WHERE site=? AND user=?", (ug.site, ug.user))
            rows = [(ug.site, ug.user, a, t) for a, ts in ug.history.items() for t in ts]
            c.executemany("INSERT INTO user_history VALUES(?,?,?,?)", rows)
            c.commit()

    def delete_user(self, site: str, user: str):
        with self._lock:
            ids = [r["entity_id"] for r in self._conn.execute(
                "SELECT entity_id FROM entities WHERE site=? AND user=?", (site, user))]
            for entity_id in ids:
                self._conn.execute(
                    "DELETE FROM relation_facts WHERE site=? AND user=? AND "
                    "(subject_id=? OR object_id=?)", (site, user, entity_id, entity_id))
                self._conn.execute(
                    "DELETE FROM entity_relations WHERE site=? AND user=? AND "
                    "(subject_id=? OR object_id=?)", (site, user, entity_id, entity_id))
                self._conn.execute("DELETE FROM entity_fields WHERE entity_id=?", (entity_id,))
                self._conn.execute(
                    "DELETE FROM entity_aliases WHERE site=? AND user=? AND entity_id=?",
                    (site, user, entity_id))
                self._conn.execute(
                    "DELETE FROM entities WHERE site=? AND user=? AND entity_id=?",
                    (site, user, entity_id))
            assoc_pairs = [
                (r["a"], r["b"]) for r in self._conn.execute(
                    "SELECT a,b FROM assoc_edge_users WHERE site=? AND user=?",
                    (site, user))
            ]
            self._conn.execute(
                "DELETE FROM assoc_edge_users WHERE site=? AND user=?", (site, user))
            self._refresh_assoc_user_counts(site, assoc_pairs, delete_empty=True)
            for t in ("user_edges", "user_numeric", "user_history", "events", "consents"):
                self._conn.execute(f"DELETE FROM {t} WHERE site=? AND user=?", (site, user))
            self._conn.execute(
                "DELETE FROM canonicalization_suggestions WHERE site=? AND user=?",
                (site, user))
            self._conn.execute(
                "DELETE FROM document_tags WHERE site=? AND user=?", (site, user))
            self._conn.execute(
                "DELETE FROM documents WHERE site=? AND user=?", (site, user))
            self._conn.execute(
                "DELETE FROM assets WHERE site=? AND user=?", (site, user))
            self._conn.commit()

    def export_user(self, site: str, user: str) -> Dict:
        ug = self.load_user(site, user)
        evs = self.recall(site, user, limit=100000)
        return {"site": site, "user": user,
                "edges": {a: e.__dict__ for a, e in ug.edges.items()},
                "numeric": ug.numeric, "events": evs,
                "consent": self.has_consent(site, user)}

    # ---- assoc graph (per site) ----
    def load_assoc(self, site: str, user: str = None, min_users: int = 1) -> AssocGraph:
        ag = AssocGraph(site)
        min_users = int(min_users or 1)
        if min_users <= 1:
            rows = self._conn.execute(
                "SELECT a,b,weight FROM assoc_edges WHERE site=?", (site,))
        elif user is None:
            rows = self._conn.execute(
                "SELECT a,b,weight FROM assoc_edges WHERE site=? AND users>=?",
                (site, min_users))
        else:
            rows = self._conn.execute(
                "SELECT e.a,e.b,e.weight FROM assoc_edges e "
                "LEFT JOIN assoc_edge_users u ON u.site=e.site AND u.a=e.a "
                "AND u.b=e.b AND u.user=? "
                "WHERE e.site=? AND (e.users>=? OR u.user IS NOT NULL)",
                (user, site, min_users))
        for r in rows:
            ag.edges[(r["a"], r["b"])] = r["weight"]
        return ag

    def save_assoc(self, ag: AssocGraph, contributor_user: str = None, touched_pairs=None):
        touched_pairs = [self._assoc_key(a, b) for a, b in (touched_pairs or [])]
        with self._lock:
            self._conn.executemany(
                "INSERT INTO assoc_edges(site,a,b,weight) VALUES(?,?,?,?) "
                "ON CONFLICT(site,a,b) DO UPDATE SET weight=excluded.weight",
                [(ag.site, k[0], k[1], v) for k, v in ag.edges.items()])
            if contributor_user and touched_pairs:
                self._conn.executemany(
                    "INSERT INTO assoc_edge_users(site,user,a,b,hits) VALUES(?,?,?,?,1) "
                    "ON CONFLICT(site,user,a,b) DO UPDATE SET hits=hits+1",
                    [(ag.site, contributor_user, a, b) for a, b in touched_pairs])
                self._refresh_assoc_user_counts(ag.site, touched_pairs)
            self._conn.commit()

    # ---- cabinet (events) ----
    def append_event(self, ev: Event):
        with self._lock:
            cursor = self._conn.execute(
                "INSERT INTO events(site,user,ts,type,payload,attrs) VALUES(?,?,?,?,?,?)",
                (ev.site, ev.user, ev.ts, ev.type, json.dumps(ev.payload),
                 json.dumps(ev.attrs)))
            self._conn.commit()
            return int(cursor.lastrowid)

    def recall(self, site: str, user: str, type: Optional[str] = None,
               contains: Optional[str] = None, limit: int = 20) -> List[Dict]:
        q = "SELECT ts,type,payload,attrs FROM events WHERE site=? AND user=?"
        args = [site, user]
        if type:
            q += " AND type=?"; args.append(type)
        if contains:
            q += " AND payload LIKE ?"; args.append(f"%{contains}%")
        q += " ORDER BY ts DESC LIMIT ?"; args.append(limit)
        out = []
        for r in self._conn.execute(q, args):
            out.append({"ts": r["ts"], "type": r["type"],
                        "payload": json.loads(r["payload"]), "attrs": json.loads(r["attrs"])})
        return out

    def events_chronological(self, site: str, user: str) -> List[Dict]:
        """Return stored events in stable replay order for selective forgetting."""
        rows = self._conn.execute(
            "SELECT id,ts,type,payload,attrs FROM events "
            "WHERE site=? AND user=? ORDER BY id ASC",
            (site, user),
        )
        return [
            {
                "id": row["id"],
                "ts": row["ts"],
                "type": row["type"],
                "payload": json.loads(row["payload"]),
                "attrs": json.loads(row["attrs"]),
            }
            for row in rows
        ]

    def events_site_chronological(self, site: str) -> List[Dict]:
        """Return all site events in stable write order for assoc rebuilding."""
        rows = self._conn.execute(
            "SELECT id,user,attrs FROM events WHERE site=? ORDER BY id ASC",
            (site,),
        )
        return [
            {"id": row["id"], "user": row["user"],
             "attrs": json.loads(row["attrs"])}
            for row in rows
        ]

    def replace_assoc_site(self, ag: AssocGraph, contributor_hits: Dict):
        """Replace one site's derived assoc state after evidence deletion."""
        rows = [
            (ag.site, user, a, b, int(hits))
            for (user, a, b), hits in contributor_hits.items()
            if int(hits) > 0
        ]
        users_by_pair = {}
        for _site, user, a, b, _hits in rows:
            users_by_pair.setdefault((a, b), set()).add(user)
        with self._lock:
            self._conn.execute(
                "DELETE FROM assoc_edge_users WHERE site=?", (ag.site,))
            self._conn.execute("DELETE FROM assoc_edges WHERE site=?", (ag.site,))
            self._conn.executemany(
                "INSERT INTO assoc_edges(site,a,b,weight,users) VALUES(?,?,?,?,?)",
                [(ag.site, a, b, weight, len(users_by_pair.get((a, b), set())))
                 for (a, b), weight in ag.edges.items()],
            )
            self._conn.executemany(
                "INSERT INTO assoc_edge_users(site,user,a,b,hits) VALUES(?,?,?,?,?)",
                rows,
            )
            self._conn.commit()

    def delete_document_artifacts(self, site: str, user: str,
                                  source_sha256: str,
                                  document_id: str = None) -> Dict:
        """Delete exact document events and queue rows, returning removed events."""
        with self._lock:
            event_rows = self._conn.execute(
                "SELECT id,ts,type,payload,attrs FROM events "
                "WHERE site=? AND user=? ORDER BY id ASC",
                (site, user),
            ).fetchall()
            removed = []
            for row in event_rows:
                payload = json.loads(row["payload"])
                if not (payload.get("source_sha256") == source_sha256 or (
                        document_id and payload.get("document_id") == document_id)):
                    continue
                removed.append({
                    "id": row["id"],
                    "ts": row["ts"],
                    "type": row["type"],
                    "payload": payload,
                    "attrs": json.loads(row["attrs"]),
                })

            suggestion_rows = self._conn.execute(
                "SELECT suggestion_id,payload FROM canonicalization_suggestions "
                "WHERE site=? AND user=?",
                (site, user),
            ).fetchall()
            suggestion_ids = [
                row["suggestion_id"]
                for row in suggestion_rows
                if (json.loads(row["payload"]).get("source_sha256") == source_sha256 or
                    (document_id and json.loads(row["payload"]).get("document_id") == document_id))
            ]
            if removed:
                self._conn.executemany(
                    "DELETE FROM events WHERE id=?",
                    [(row["id"],) for row in removed],
                )
            if suggestion_ids:
                self._conn.executemany(
                    "DELETE FROM canonicalization_suggestions WHERE suggestion_id=?",
                    [(suggestion_id,) for suggestion_id in suggestion_ids],
                )
            self._conn.commit()
        return {"events": removed, "suggestions_deleted": len(suggestion_ids)}

    # ---- durable document catalog and approved tag provenance ----
    @staticmethod
    def _document_row(row):
        if row is None:
            return None
        out = dict(row)
        out["pinned"] = bool(out["pinned"])
        out["authoritative"] = bool(out["authoritative"])
        return out

    def insert_document(self, row: Dict):
        with self._lock:
            self._conn.execute(
                "INSERT INTO documents(document_id,site,user,source_sha256,source_name,"
                "markdown_path,envelope_path,mime_type,extraction_quality,warning_count,"
                "block_count,created_ts,imported_ts,status,pinned,authoritative,superseded_by) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (row["document_id"], row["site"], row["user"], row["source_sha256"],
                 row["source_name"], row["markdown_path"], row["envelope_path"],
                 row["mime_type"], row["extraction_quality"], int(row["warning_count"]),
                 int(row["block_count"]), float(row["created_ts"]),
                 float(row["imported_ts"]), row["status"], int(row.get("pinned", False)),
                 int(row.get("authoritative", False)), row.get("superseded_by", "")),
            )
            self._conn.commit()
        return self.get_document(row["site"], row["user"], row["document_id"])

    def get_document(self, site: str, user: str, document_id_or_sha256: str):
        row = self._conn.execute(
            "SELECT * FROM documents WHERE site=? AND user=? "
            "AND (document_id=? OR source_sha256=?) LIMIT 1",
            (site, user, document_id_or_sha256, document_id_or_sha256),
        ).fetchone()
        return self._document_row(row)

    def list_documents(self, site: str, user: str, statuses=None,
                       limit: int = 100, offset: int = 0) -> List[Dict]:
        statuses = list(statuses or ["active"])
        if not statuses:
            return []
        marks = ",".join("?" for _ in statuses)
        rows = self._conn.execute(
            "SELECT * FROM documents WHERE site=? AND user=? AND status IN (" +
            marks + ") ORDER BY pinned DESC,imported_ts DESC,document_id ASC LIMIT ? OFFSET ?",
            (site, user, *statuses, int(limit), int(offset)),
        ).fetchall()
        return [self._document_row(row) for row in rows]

    def count_documents(self, site: str, user: str, statuses=None) -> int:
        statuses = list(statuses or ["active"])
        if not statuses:
            return 0
        marks = ",".join("?" for _ in statuses)
        row = self._conn.execute(
            "SELECT COUNT(*) AS n FROM documents WHERE site=? AND user=? "
            "AND status IN (" + marks + ")",
            (site, user, *statuses),
        ).fetchone()
        return int(row["n"])

    def update_document(self, site: str, user: str, document_id: str, **changes):
        allowed = {"status", "pinned", "authoritative", "superseded_by"}
        items = [(key, value) for key, value in changes.items() if key in allowed]
        if not items:
            return self.get_document(site, user, document_id)
        sets = ",".join(key + "=?" for key, _value in items)
        values = [int(value) if key in ("pinned", "authoritative") else value
                  for key, value in items]
        with self._lock:
            self._conn.execute(
                "UPDATE documents SET " + sets +
                " WHERE site=? AND user=? AND document_id=?",
                (*values, site, user, document_id),
            )
            self._conn.commit()
        return self.get_document(site, user, document_id)

    def add_document_tags(self, site: str, user: str, document_id: str,
                          tags, suggestion_id: str, approved_ts: float):
        rows = [(document_id, site, user, tag, "human_approved",
                 suggestion_id or "", float(approved_ts)) for tag in tags]
        with self._lock:
            self._conn.executemany(
                "INSERT INTO document_tags(document_id,site,user,tag,provenance,"
                "suggestion_id,approved_ts) VALUES(?,?,?,?,?,?,?) "
                "ON CONFLICT(document_id,tag) DO UPDATE SET "
                "provenance=excluded.provenance,suggestion_id=excluded.suggestion_id,"
                "approved_ts=excluded.approved_ts",
                rows,
            )
            self._conn.commit()
        return self.list_document_tags(site, user, document_id)

    def list_document_tags(self, site: str, user: str,
                           document_id: str = None) -> List[Dict]:
        query = "SELECT * FROM document_tags WHERE site=? AND user=?"
        args = [site, user]
        if document_id:
            query += " AND document_id=?"
            args.append(document_id)
        query += " ORDER BY tag,document_id"
        return [dict(row) for row in self._conn.execute(query, args)]

    def delete_document_catalog(self, site: str, user: str, document_id: str):
        with self._lock:
            tags = self._conn.execute(
                "SELECT tag FROM document_tags WHERE site=? AND user=? AND document_id=?",
                (site, user, document_id),
            ).fetchall()
            self._conn.execute(
                "DELETE FROM document_tags WHERE site=? AND user=? AND document_id=?",
                (site, user, document_id),
            )
            cursor = self._conn.execute(
                "DELETE FROM documents WHERE site=? AND user=? AND document_id=?",
                (site, user, document_id),
            )
            self._conn.commit()
        return {"documents_deleted": int(cursor.rowcount),
                "tag_mappings_deleted": len(tags)}

    # ---- local media asset metadata (bytes remain in the blob store) ----
    @staticmethod
    def _asset_row(row):
        if row is None:
            return None
        out = dict(row)
        for key in ("exif_stripped", "sensitive", "consent"):
            out[key] = bool(out[key])
        return out

    def insert_asset(self, row: Dict):
        with self._lock:
            self._conn.execute(
                "INSERT INTO assets(id,site,user,type,mime,uri,sha256,bytes,created_ts,"
                "source,thumbnail_uri,exif_stripped,sensitive,consent,status) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (row["id"], row["site"], row["user"], row["type"], row["mime"],
                 row["uri"], row["sha256"], int(row["bytes"]), row["created_ts"],
                 row["source"], row["thumbnail_uri"], int(row["exif_stripped"]),
                 int(row["sensitive"]), int(row["consent"]), row["status"]),
            )
            self._conn.commit()
        return self.get_asset(row["site"], row["user"], row["id"])

    def get_asset(self, site: str, user: str, asset_id_or_sha256: str,
                  status: str = "active"):
        row = self._conn.execute(
            "SELECT * FROM assets WHERE site=? AND user=? AND status=? "
            "AND (id=? OR sha256=?) ORDER BY created_ts DESC LIMIT 1",
            (site, user, status, asset_id_or_sha256, asset_id_or_sha256),
        ).fetchone()
        return self._asset_row(row)

    def list_assets(self, site: str, user: str, status: str = "active",
                    limit: int = 100) -> List[Dict]:
        rows = self._conn.execute(
            "SELECT * FROM assets WHERE site=? AND user=? AND status=? "
            "ORDER BY created_ts DESC,id ASC LIMIT ?",
            (site, user, status, int(limit)),
        ).fetchall()
        return [self._asset_row(row) for row in rows]

    def set_asset_sensitive(self, site: str, user: str, asset_id: str,
                            sensitive: bool):
        with self._lock:
            self._conn.execute(
                "UPDATE assets SET sensitive=? WHERE site=? AND user=? "
                "AND id=? AND status='active'",
                (int(sensitive), site, user, asset_id),
            )
            self._conn.commit()
        return self.get_asset(site, user, asset_id)

    def delete_asset_row(self, site: str, user: str, asset_id: str):
        with self._lock:
            self._conn.execute(
                "DELETE FROM assets WHERE site=? AND user=? AND id=?",
                (site, user, asset_id),
            )
            self._conn.commit()

    def delete_asset_artifacts(self, site: str, user: str, asset_id: str,
                               source_sha256: str) -> Dict:
        with self._lock:
            event_rows = self._conn.execute(
                "SELECT id,ts,type,payload,attrs FROM events "
                "WHERE site=? AND user=? AND type='asset' ORDER BY id ASC",
                (site, user),
            ).fetchall()
            removed = []
            for row in event_rows:
                payload = json.loads(row["payload"])
                if payload.get("asset_id") != asset_id:
                    continue
                removed.append({
                    "id": row["id"], "ts": row["ts"], "type": row["type"],
                    "payload": payload, "attrs": json.loads(row["attrs"]),
                })
            suggestion_rows = self._conn.execute(
                "SELECT suggestion_id,payload FROM canonicalization_suggestions "
                "WHERE site=? AND user=?", (site, user)).fetchall()
            suggestion_ids = []
            for row in suggestion_rows:
                payload = json.loads(row["payload"])
                if (payload.get("asset_id") == asset_id or
                        payload.get("source_sha256") == source_sha256):
                    suggestion_ids.append(row["suggestion_id"])
            if removed:
                self._conn.executemany(
                    "DELETE FROM events WHERE id=?",
                    [(row["id"],) for row in removed])
            if suggestion_ids:
                self._conn.executemany(
                    "DELETE FROM canonicalization_suggestions WHERE suggestion_id=?",
                    [(suggestion_id,) for suggestion_id in suggestion_ids])
            self._conn.execute(
                "UPDATE assets SET status='tombstoned',uri='',thumbnail_uri='' "
                "WHERE site=? AND user=? AND id=?",
                (site, user, asset_id),
            )
            self._conn.commit()
        return {"events": removed, "suggestions_deleted": len(suggestion_ids)}

    # ---- prior ----
    def load_prior(self, site: str) -> PopulationPrior:
        pp = PopulationPrior(site)
        for r in self._conn.execute("SELECT attr,sum,n FROM prior_node WHERE site=?", (site,)):
            pp._sum[r["attr"]] = r["sum"]; pp._n[r["attr"]] = r["n"]
        m = self._conn.execute("SELECT n_users FROM prior_meta WHERE site=?", (site,)).fetchone()
        pp.n_users = m["n_users"] if m else 0
        return pp

    def save_prior(self, pp: PopulationPrior):
        with self._lock:
            self._conn.executemany(
                "INSERT INTO prior_node VALUES(?,?,?,?) "
                "ON CONFLICT(site,attr) DO UPDATE SET sum=excluded.sum, n=excluded.n",
                [(pp.site, a, pp._sum[a], pp._n[a]) for a in pp._sum])
            self._conn.execute(
                "INSERT INTO prior_meta VALUES(?,?) "
                "ON CONFLICT(site) DO UPDATE SET n_users=excluded.n_users",
                (pp.site, pp.n_users))
            self._conn.commit()

    # ---- identity links (the supernode wiring; created when a user signs in) ----
    def link_identity(self, person: str, site: str, local_user: str, ts: float = 0.0):
        with self._lock:
            self._conn.execute(
                "INSERT OR IGNORE INTO identities(person,site,local_user,ts) VALUES(?,?,?,?)",
                (person, site, local_user, ts))
            self._conn.commit()

    def unlink_identity(self, person: str, site: str, local_user: str):
        with self._lock:
            self._conn.execute(
                "DELETE FROM identities WHERE person=? AND site=? AND local_user=?",
                (person, site, local_user))
            self._conn.commit()

    def list_identities(self, person: str):
        return [(r["site"], r["local_user"]) for r in self._conn.execute(
            "SELECT site, local_user FROM identities WHERE person=?", (person,))]

    # ---- per-site sharing policy (what a target site may see) ----
    def set_share(self, person: str, target_site: str, category: str, allowed: bool):
        with self._lock:
            self._conn.execute(
                "INSERT INTO share_policy(person,target_site,category,allowed) VALUES(?,?,?,?) "
                "ON CONFLICT(person,target_site,category) DO UPDATE SET allowed=excluded.allowed",
                (person, target_site, category, int(allowed)))
            self._conn.commit()

    def get_shares(self, person: str, target_site: str):
        return {r["category"]: bool(r["allowed"]) for r in self._conn.execute(
            "SELECT category, allowed FROM share_policy WHERE person=? AND target_site=?",
            (person, target_site))}

    # ---- typed entity layer ----
    def create_entity(self, entity_id: str, site: str, user: str, kind: str,
                      display_name: str, created_at: float):
        with self._lock:
            self._conn.execute(
                "INSERT INTO entities(entity_id,site,user,kind,display_name,created_at) "
                "VALUES(?,?,?,?,?,?)",
                (entity_id, site, user, kind, display_name, created_at))
            self._conn.commit()

    def get_entity(self, site: str, user: str, entity_id: str):
        row = self._conn.execute(
            "SELECT * FROM entities WHERE site=? AND user=? AND entity_id=?",
            (site, user, entity_id)).fetchone()
        return dict(row) if row else None

    def entity_by_alias(self, site: str, user: str, alias_attr: str):
        row = self._conn.execute(
            "SELECT e.* FROM entity_aliases a JOIN entities e ON e.entity_id=a.entity_id "
            "WHERE a.site=? AND a.user=? AND a.alias_attr=?",
            (site, user, alias_attr)).fetchone()
        return dict(row) if row else None

    def link_entity_alias(self, site: str, user: str, entity_id: str, alias_attr: str,
                          source: str = "stated", confidence: float = 1.0):
        with self._lock:
            self._conn.execute(
                "INSERT INTO entity_aliases(site,user,alias_attr,entity_id,source,confidence) "
                "VALUES(?,?,?,?,?,?) "
                "ON CONFLICT(site,user,alias_attr) DO UPDATE SET "
                "entity_id=excluded.entity_id, source=excluded.source, confidence=excluded.confidence",
                (site, user, alias_attr, entity_id, source, float(confidence)))
            self._conn.commit()

    def unlink_entity_alias(self, site: str, user: str, entity_id: str, alias_attr: str):
        with self._lock:
            self._conn.execute(
                "DELETE FROM entity_aliases WHERE site=? AND user=? AND entity_id=? AND alias_attr=?",
                (site, user, entity_id, alias_attr))
            self._conn.commit()

    def list_entity_aliases(self, site: str, user: str, entity_id: str):
        return [dict(r) for r in self._conn.execute(
            "SELECT * FROM entity_aliases WHERE site=? AND user=? AND entity_id=? ORDER BY alias_attr",
            (site, user, entity_id))]

    def list_entities(self, site: str, user: str):
        return [dict(r) for r in self._conn.execute(
            "SELECT * FROM entities WHERE site=? AND user=? ORDER BY display_name,entity_id",
            (site, user))]

    def update_entity_kind(self, site: str, user: str, entity_id: str, kind: str):
        with self._lock:
            self._conn.execute(
                "UPDATE entities SET kind=? WHERE site=? AND user=? AND entity_id=?",
                (kind, site, user, entity_id))
            self._conn.commit()

    def set_entity_field(self, entity_id: str, field: str, value: str,
                         provenance: str, ts: float):
        with self._lock:
            self._conn.execute(
                "INSERT INTO entity_fields(entity_id,field,value,provenance,ts) VALUES(?,?,?,?,?) "
                "ON CONFLICT(entity_id,field) DO UPDATE SET "
                "value=excluded.value, provenance=excluded.provenance, ts=excluded.ts",
                (entity_id, field, value, provenance, float(ts)))
            self._conn.commit()

    def list_entity_fields(self, entity_id: str):
        return [dict(r) for r in self._conn.execute(
            "SELECT * FROM entity_fields WHERE entity_id=? ORDER BY field", (entity_id,))]

    def get_entity_relation(self, site: str, user: str, subject_id: str,
                            relation: str, object_id: str):
        row = self._conn.execute(
            "SELECT * FROM entity_relations WHERE site=? AND user=? AND subject_id=? "
            "AND relation=? AND object_id=?",
            (site, user, subject_id, relation, object_id)).fetchone()
        return dict(row) if row else None

    def upsert_entity_relation(self, row: Dict):
        with self._lock:
            self._conn.execute(
                "INSERT INTO entity_relations(site,user,subject_id,relation,object_id,"
                "weight,confidence,hits,last_reinforced,salience,provenance,note) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(site,user,subject_id,relation,object_id) DO UPDATE SET "
                "weight=excluded.weight, confidence=excluded.confidence, hits=excluded.hits, "
                "last_reinforced=excluded.last_reinforced, salience=excluded.salience, "
                "provenance=excluded.provenance, note=excluded.note",
                (row["site"], row["user"], row["subject_id"], row["relation"],
                 row["object_id"], row["weight"], row["confidence"], row["hits"],
                 row["last_reinforced"], row["salience"], row["provenance"], row["note"]))
            self._conn.commit()

    def list_entity_relations(self, site: str, user: str, entity_id: str = None):
        if entity_id is None:
            rows = self._conn.execute(
                "SELECT * FROM entity_relations WHERE site=? AND user=? "
                "ORDER BY subject_id,relation,object_id", (site, user))
        else:
            rows = self._conn.execute(
                "SELECT * FROM entity_relations WHERE site=? AND user=? "
                "AND (subject_id=? OR object_id=?) ORDER BY relation,subject_id,object_id",
                (site, user, entity_id, entity_id))
        return [dict(r) for r in rows]

    def get_relation_fact(self, fact_id: str):
        row = self._conn.execute(
            "SELECT * FROM relation_facts WHERE fact_id=?", (fact_id,)).fetchone()
        return dict(row) if row else None

    def get_relation_fact_by_note(self, site: str, user: str, subject_id: str,
                                  relation: str, object_id: str, note: str):
        row = self._conn.execute(
            "SELECT * FROM relation_facts WHERE site=? AND user=? AND subject_id=? "
            "AND relation=? AND object_id=? AND note=?",
            (site, user, subject_id, relation, object_id, note)).fetchone()
        return dict(row) if row else None

    def upsert_relation_fact(self, row: Dict):
        with self._lock:
            existing = self.get_relation_fact_by_note(
                row["site"], row["user"], row["subject_id"], row["relation"],
                row["object_id"], row["note"])
            if existing:
                self._conn.execute(
                    "UPDATE relation_facts SET ts=?, provenance=?, event_id=? WHERE fact_id=?",
                    (row["ts"], row["provenance"], row.get("event_id"), existing["fact_id"]))
                self._conn.commit()
                updated = self.get_relation_fact(existing["fact_id"])
                updated["created"] = False
                return updated
            self._conn.execute(
                "INSERT INTO relation_facts(fact_id,site,user,subject_id,relation,object_id,"
                "note,ts,provenance,event_id) VALUES(?,?,?,?,?,?,?,?,?,?)",
                (row["fact_id"], row["site"], row["user"], row["subject_id"],
                 row["relation"], row["object_id"], row["note"], row["ts"],
                 row["provenance"], row.get("event_id")))
            self._conn.commit()
            created = self.get_relation_fact(row["fact_id"])
            created["created"] = True
            return created

    def list_relation_facts(self, site: str, user: str, subject_id: str,
                            relation: str, object_id: str, limit: int = 5):
        return [dict(r) for r in self._conn.execute(
            "SELECT * FROM relation_facts WHERE site=? AND user=? AND subject_id=? "
            "AND relation=? AND object_id=? ORDER BY ts DESC, fact_id DESC LIMIT ?",
            (site, user, subject_id, relation, object_id, int(limit)))]

    def delete_relation_fact(self, fact_id: str) -> bool:
        with self._lock:
            cur = self._conn.execute(
                "DELETE FROM relation_facts WHERE fact_id=?", (fact_id,))
            self._conn.commit()
            return cur.rowcount > 0

    def delete_entity_relation(self, site: str, user: str, subject_id: str,
                               relation: str, object_id: str):
        with self._lock:
            self._conn.execute(
                "DELETE FROM relation_facts WHERE site=? AND user=? AND subject_id=? "
                "AND relation=? AND object_id=?",
                (site, user, subject_id, relation, object_id))
            self._conn.execute(
                "DELETE FROM entity_relations WHERE site=? AND user=? AND subject_id=? "
                "AND relation=? AND object_id=?",
                (site, user, subject_id, relation, object_id))
            self._conn.commit()

    def delete_entity(self, site: str, user: str, entity_id: str):
        with self._lock:
            self._conn.execute(
                "DELETE FROM relation_facts WHERE site=? AND user=? AND "
                "(subject_id=? OR object_id=?)", (site, user, entity_id, entity_id))
            self._conn.execute(
                "DELETE FROM entity_relations WHERE site=? AND user=? AND "
                "(subject_id=? OR object_id=?)", (site, user, entity_id, entity_id))
            self._conn.execute("DELETE FROM entity_fields WHERE entity_id=?", (entity_id,))
            self._conn.execute(
                "DELETE FROM entity_aliases WHERE site=? AND user=? AND entity_id=?",
                (site, user, entity_id))
            self._conn.execute(
                "DELETE FROM entities WHERE site=? AND user=? AND entity_id=?",
                (site, user, entity_id))
            self._conn.execute(
                "DELETE FROM canonicalization_suggestions WHERE site=? AND user=? "
                "AND (payload LIKE ? OR payload LIKE ? OR payload LIKE ?)",
                (site, user, f'%"entity_id":"{entity_id}"%',
                 f'%"subject_id":"{entity_id}"%', f'%"object_id":"{entity_id}"%'))
            self._conn.commit()

    def count_entity_references(self, entity_id: str) -> int:
        queries = [
            ("entities", "entity_id=?"),
            ("entity_aliases", "entity_id=?"),
            ("entity_fields", "entity_id=?"),
            ("entity_relations", "subject_id=? OR object_id=?"),
            ("relation_facts", "subject_id=? OR object_id=?"),
        ]
        total = 0
        for table, where in queries:
            args = (entity_id, entity_id) if " OR " in where else (entity_id,)
            total += self._conn.execute(
                f"SELECT COUNT(*) n FROM {table} WHERE {where}", args).fetchone()["n"]
        return total

    # ---- suggest-and-approve canonicalization queue ----
    @staticmethod
    def _suggestion_row(row):
        out = dict(row)
        out["payload"] = json.loads(out["payload"])
        return out

    def upsert_suggestion(self, row: Dict):
        payload = json.dumps(row["payload"], sort_keys=True, separators=(",", ":"))
        with self._lock:
            existing = self._conn.execute(
                "SELECT status FROM canonicalization_suggestions WHERE suggestion_id=?",
                (row["suggestion_id"],)).fetchone()
            if existing:
                if existing["status"] == "pending":
                    self._conn.execute(
                        "UPDATE canonicalization_suggestions SET payload=?, score=? "
                        "WHERE suggestion_id=?",
                        (payload, float(row["score"]), row["suggestion_id"]))
                self._conn.commit()
                return self.get_suggestion(row["suggestion_id"])
            self._conn.execute(
                "INSERT INTO canonicalization_suggestions("
                "suggestion_id,site,user,kind,payload,score,status,created_ts,decided_ts) "
                "VALUES(?,?,?,?,?,?,?,?,?)",
                (row["suggestion_id"], row["site"], row["user"], row["kind"],
                 payload, float(row["score"]), row["status"], float(row["created_ts"]),
                 row.get("decided_ts")))
            self._conn.commit()
            return self.get_suggestion(row["suggestion_id"])

    def get_suggestion(self, suggestion_id: str):
        row = self._conn.execute(
            "SELECT * FROM canonicalization_suggestions WHERE suggestion_id=?",
            (suggestion_id,)).fetchone()
        return self._suggestion_row(row) if row else None

    def list_suggestions(self, site: str, user: str, status: str = None):
        q = "SELECT * FROM canonicalization_suggestions WHERE site=? AND user=?"
        args = [site, user]
        if status:
            q += " AND status=?"
            args.append(status)
        q += " ORDER BY score DESC, created_ts ASC, suggestion_id ASC"
        return [self._suggestion_row(r) for r in self._conn.execute(q, args)]

    def decide_suggestion(self, suggestion_id: str, status: str, decided_ts: float):
        with self._lock:
            self._conn.execute(
                "UPDATE canonicalization_suggestions SET status=?, decided_ts=? "
                "WHERE suggestion_id=?",
                (status, float(decided_ts), suggestion_id))
            self._conn.commit()
        return self.get_suggestion(suggestion_id)

    def purge_expired_suggestions(self, site: str, user: str, now: float, ttl_days: float):
        cutoff = float(now) - float(ttl_days)
        with self._lock:
            cur = self._conn.execute(
                "DELETE FROM canonicalization_suggestions WHERE site=? AND user=? "
                "AND status='pending' AND created_ts<?",
                (site, user, cutoff))
            self._conn.commit()
            return cur.rowcount

    def trim_pending_suggestions(self, site: str, user: str, cap: int):
        pending = self.list_suggestions(site, user, "pending")
        if len(pending) <= cap:
            return 0
        drop = pending[int(cap):]
        with self._lock:
            self._conn.executemany(
                "DELETE FROM canonicalization_suggestions WHERE suggestion_id=?",
                [(row["suggestion_id"],) for row in drop])
            self._conn.commit()
        return len(drop)

    def delete_suggestions_for_entity(self, site: str, user: str, entity_id: str):
        rows = self.list_suggestions(site, user)
        ids = [
            row["suggestion_id"] for row in rows
            if row["payload"].get("entity_id") == entity_id
            or row["payload"].get("subject_id") == entity_id
            or row["payload"].get("object_id") == entity_id
        ]
        if not ids:
            return 0
        with self._lock:
            self._conn.executemany(
                "DELETE FROM canonicalization_suggestions WHERE suggestion_id=?",
                [(sid,) for sid in ids])
            self._conn.commit()
        return len(ids)

    # ---- verifiable audit log (#4) ----
    def append_audit(self, site, user, ts, action, detail, key):
        with self._lock:
            r = self._conn.execute(
                "SELECT seq, hash FROM audit WHERE site=? AND user=? ORDER BY seq DESC LIMIT 1",
                (site, user)).fetchone()
            seq = (r["seq"] + 1) if r else 0
            prev = r["hash"] if r else GENESIS
            h = entry_hash(key, prev, seq, ts, action, detail)
            self._conn.execute("INSERT INTO audit VALUES(?,?,?,?,?,?,?,?)",
                               (site, user, seq, ts, action, json.dumps(detail), prev, h))
            self._conn.commit()
            return {"seq": seq, "hash": h}

    def read_audit(self, site, user):
        return [{"seq": r["seq"], "ts": r["ts"], "action": r["action"],
                 "detail": json.loads(r["detail"]), "hash": r["hash"]}
                for r in self._conn.execute(
                    "SELECT * FROM audit WHERE site=? AND user=? ORDER BY seq", (site, user))]

    def list_users(self, site):
        return [r["user"] for r in self._conn.execute(
            "SELECT DISTINCT user FROM user_edges WHERE site=?", (site,))]
