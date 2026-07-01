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
  change_count INTEGER DEFAULT 0, first_seen_ts REAL, last_changed_ts REAL,
  last_change_counted_ts REAL,
  PRIMARY KEY(site, user, attr));
CREATE TABLE IF NOT EXISTS user_numeric(
  site TEXT, user TEXT, key TEXT, value TEXT,
  PRIMARY KEY(site, user, key));
CREATE TABLE IF NOT EXISTS user_history(
  site TEXT, user TEXT, attr TEXT, ts REAL);
CREATE TABLE IF NOT EXISTS assoc_edges(
  site TEXT, a TEXT, b TEXT, weight REAL,
  PRIMARY KEY(site, a, b));
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
CREATE TABLE IF NOT EXISTS audit(
  site TEXT, user TEXT, seq INTEGER, ts REAL, action TEXT, detail TEXT,
  prev_hash TEXT, hash TEXT, PRIMARY KEY(site, user, seq));
CREATE INDEX IF NOT EXISTS idx_events_user ON events(site, user, ts);
CREATE INDEX IF NOT EXISTS idx_hist_user ON user_history(site, user, attr);
CREATE INDEX IF NOT EXISTS idx_relation_facts_relation
  ON relation_facts(site, user, subject_id, relation, object_id, ts);
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
        migrations = {
            "fast": "REAL DEFAULT 0",
            "salience": "REAL DEFAULT 0",
            "provenance": "TEXT NOT NULL DEFAULT 'inferred'",
            "change_count": "INTEGER DEFAULT 0",
            "first_seen_ts": "REAL",
            "last_changed_ts": "REAL",
            "last_change_counted_ts": "REAL",
        }
        for col, decl in migrations.items():
            if col not in cols:
                self._conn.execute(f"ALTER TABLE user_edges ADD COLUMN {col} {decl}")

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

    # ---- user graph ----
    def load_user(self, site: str, user: str) -> UserGraph:
        ug = UserGraph(site, user)
        for r in self._conn.execute(
                "SELECT * FROM user_edges WHERE site=? AND user=?", (site, user)):
            keys = r.keys()
            ug.edges[r["attr"]] = Edge(
                r["weight"], r["confidence"], r["source"],
                r["last_reinforced"], r["hits"],
                r["fast"] if "fast" in keys else 0.0,
                r["salience"] if "salience" in keys else 0.0,
                r["provenance"] if "provenance" in keys and r["provenance"] else "inferred",
                int(r["change_count"] or 0) if "change_count" in keys else 0,
                r["first_seen_ts"] if "first_seen_ts" in keys else None,
                r["last_changed_ts"] if "last_changed_ts" in keys else None,
                r["last_change_counted_ts"] if "last_change_counted_ts" in keys else None,
            )
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
                "INSERT INTO user_edges(site,user,attr,weight,confidence,source,"
                "last_reinforced,hits,fast,salience,provenance,change_count,"
                "first_seen_ts,last_changed_ts,last_change_counted_ts) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                [(ug.site, ug.user, a, e.weight, e.confidence, e.source,
                  e.last_reinforced, e.hits, e.fast, e.salience, e.provenance,
                  e.change_count, e.first_seen_ts, e.last_changed_ts,
                  e.last_change_counted_ts) for a, e in ug.edges.items()])
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
            for t in ("user_edges", "user_numeric", "user_history", "events", "consents"):
                self._conn.execute(f"DELETE FROM {t} WHERE site=? AND user=?", (site, user))
            self._conn.commit()

    def export_user(self, site: str, user: str) -> Dict:
        ug = self.load_user(site, user)
        evs = self.recall(site, user, limit=100000)
        return {"site": site, "user": user,
                "edges": {a: e.__dict__ for a, e in ug.edges.items()},
                "numeric": ug.numeric, "events": evs,
                "consent": self.has_consent(site, user)}

    # ---- assoc graph (per site) ----
    def load_assoc(self, site: str) -> AssocGraph:
        ag = AssocGraph(site)
        for r in self._conn.execute("SELECT a,b,weight FROM assoc_edges WHERE site=?", (site,)):
            ag.edges[(r["a"], r["b"])] = r["weight"]
        return ag

    def save_assoc(self, ag: AssocGraph):
        with self._lock:
            self._conn.executemany(
                "INSERT INTO assoc_edges VALUES(?,?,?,?) "
                "ON CONFLICT(site,a,b) DO UPDATE SET weight=excluded.weight",
                [(ag.site, k[0], k[1], v) for k, v in ag.edges.items()])
            self._conn.commit()

    # ---- cabinet (events) ----
    def append_event(self, ev: Event):
        with self._lock:
            self._conn.execute(
                "INSERT INTO events(site,user,ts,type,payload,attrs) VALUES(?,?,?,?,?,?)",
                (ev.site, ev.user, ev.ts, ev.type, json.dumps(ev.payload),
                 json.dumps(ev.attrs)))
            self._conn.commit()

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
