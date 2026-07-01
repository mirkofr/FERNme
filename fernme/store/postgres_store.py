"""Postgres-backed store for FERN — same interface as SQLiteStore, for production
multi-tenant deployments. Tested against a real Postgres 16 instance (see
tests/test_postgres.py, which uses the rootless `pgserver`).

Note: `user` is reserved in Postgres, so it is quoted everywhere."""
from __future__ import annotations
import json, threading
from typing import List, Optional, Dict
import psycopg
from psycopg.rows import dict_row
from ..core.graph import UserGraph, AssocGraph, Edge, Event
from ..prior.population import PopulationPrior

SCHEMA = """
CREATE TABLE IF NOT EXISTS consents(
  site TEXT, "user" TEXT, granted INT, ts DOUBLE PRECISION,
  PRIMARY KEY(site, "user"));
CREATE TABLE IF NOT EXISTS user_edges(
  site TEXT, "user" TEXT, attr TEXT, weight DOUBLE PRECISION, confidence DOUBLE PRECISION,
  source TEXT, last_reinforced DOUBLE PRECISION, hits INT, fast DOUBLE PRECISION DEFAULT 0,
  salience DOUBLE PRECISION DEFAULT 0, provenance TEXT NOT NULL DEFAULT 'inferred',
  change_count INT DEFAULT 0, first_seen_ts DOUBLE PRECISION,
  last_changed_ts DOUBLE PRECISION, last_change_counted_ts DOUBLE PRECISION,
  PRIMARY KEY(site, "user", attr));
CREATE TABLE IF NOT EXISTS user_numeric(
  site TEXT, "user" TEXT, key TEXT, value TEXT,
  PRIMARY KEY(site, "user", key));
CREATE TABLE IF NOT EXISTS user_history(
  site TEXT, "user" TEXT, attr TEXT, ts DOUBLE PRECISION);
CREATE TABLE IF NOT EXISTS assoc_edges(
  site TEXT, a TEXT, b TEXT, weight DOUBLE PRECISION,
  PRIMARY KEY(site, a, b));
CREATE TABLE IF NOT EXISTS events(
  id BIGSERIAL PRIMARY KEY,
  site TEXT, "user" TEXT, ts DOUBLE PRECISION, type TEXT, payload TEXT, attrs TEXT);
CREATE TABLE IF NOT EXISTS prior_node(
  site TEXT, attr TEXT, sum DOUBLE PRECISION, n INT, PRIMARY KEY(site, attr));
CREATE TABLE IF NOT EXISTS prior_meta(site TEXT PRIMARY KEY, n_users INT);
CREATE TABLE IF NOT EXISTS identities(
  person TEXT, site TEXT, local_user TEXT, ts DOUBLE PRECISION,
  PRIMARY KEY(person, site, local_user));
CREATE TABLE IF NOT EXISTS share_policy(
  person TEXT, target_site TEXT, category TEXT, allowed INT,
  PRIMARY KEY(person, target_site, category));
CREATE TABLE IF NOT EXISTS entities(
  entity_id TEXT PRIMARY KEY, site TEXT NOT NULL, "user" TEXT NOT NULL,
  kind TEXT NOT NULL, display_name TEXT NOT NULL, created_at DOUBLE PRECISION NOT NULL);
CREATE TABLE IF NOT EXISTS entity_aliases(
  site TEXT NOT NULL, "user" TEXT NOT NULL, alias_attr TEXT NOT NULL,
  entity_id TEXT NOT NULL, source TEXT NOT NULL DEFAULT 'stated',
  confidence DOUBLE PRECISION NOT NULL DEFAULT 1.0,
  PRIMARY KEY(site, "user", alias_attr));
CREATE TABLE IF NOT EXISTS entity_fields(
  entity_id TEXT NOT NULL, field TEXT NOT NULL,
  value TEXT NOT NULL, provenance TEXT NOT NULL DEFAULT 'stated',
  ts DOUBLE PRECISION NOT NULL,
  PRIMARY KEY(entity_id, field));
CREATE TABLE IF NOT EXISTS entity_relations(
  site TEXT NOT NULL, "user" TEXT NOT NULL,
  subject_id TEXT NOT NULL, relation TEXT NOT NULL, object_id TEXT NOT NULL,
  weight DOUBLE PRECISION NOT NULL DEFAULT 0.0,
  confidence DOUBLE PRECISION NOT NULL DEFAULT 0.0,
  hits INT NOT NULL DEFAULT 0, last_reinforced DOUBLE PRECISION NOT NULL DEFAULT 0.0,
  salience DOUBLE PRECISION NOT NULL DEFAULT 0.0,
  provenance TEXT NOT NULL DEFAULT 'stated',
  note TEXT NOT NULL DEFAULT '',
  PRIMARY KEY(site, "user", subject_id, relation, object_id));
CREATE TABLE IF NOT EXISTS relation_facts(
  fact_id TEXT PRIMARY KEY,
  site TEXT NOT NULL, "user" TEXT NOT NULL,
  subject_id TEXT NOT NULL, relation TEXT NOT NULL, object_id TEXT NOT NULL,
  note TEXT NOT NULL DEFAULT '',
  ts DOUBLE PRECISION NOT NULL,
  provenance TEXT NOT NULL DEFAULT 'stated',
  event_id BIGINT,
  UNIQUE(site, "user", subject_id, relation, object_id, note),
  FOREIGN KEY(site, "user", subject_id, relation, object_id)
    REFERENCES entity_relations(site, "user", subject_id, relation, object_id)
    ON DELETE CASCADE);
CREATE INDEX IF NOT EXISTS idx_events_user ON events(site, "user", ts);
CREATE INDEX IF NOT EXISTS idx_hist_user ON user_history(site, "user", attr);
CREATE INDEX IF NOT EXISTS idx_relation_facts_relation
  ON relation_facts(site, "user", subject_id, relation, object_id, ts);
"""


class PostgresStore:
    def __init__(self, dsn: str):
        self.dsn = dsn
        self._lock = threading.Lock()
        self._conn = psycopg.connect(dsn, autocommit=True, row_factory=dict_row)
        self._conn.execute(SCHEMA)
        migrations = {
            "fast": "DOUBLE PRECISION DEFAULT 0",
            "salience": "DOUBLE PRECISION DEFAULT 0",
            "provenance": "TEXT NOT NULL DEFAULT 'inferred'",
            "change_count": "INT DEFAULT 0",
            "first_seen_ts": "DOUBLE PRECISION",
            "last_changed_ts": "DOUBLE PRECISION",
            "last_change_counted_ts": "DOUBLE PRECISION",
        }
        for col, decl in migrations.items():
            self._conn.execute(f"ALTER TABLE user_edges ADD COLUMN IF NOT EXISTS {col} {decl}")

    def _q(self, sql, args=()):
        return self._conn.execute(sql, args)

    # ---- consent ----
    def set_consent(self, site, user, granted, ts=0.0):
        with self._lock:
            self._q('INSERT INTO consents(site,"user",granted,ts) VALUES(%s,%s,%s,%s) '
                    'ON CONFLICT(site,"user") DO UPDATE SET granted=EXCLUDED.granted, ts=EXCLUDED.ts',
                    (site, user, int(granted), ts))

    def has_consent(self, site, user) -> bool:
        r = self._q('SELECT granted FROM consents WHERE site=%s AND "user"=%s', (site, user)).fetchone()
        return bool(r["granted"]) if r else False

    # ---- user graph ----
    def load_user(self, site, user) -> UserGraph:
        ug = UserGraph(site, user)
        for r in self._q('SELECT * FROM user_edges WHERE site=%s AND "user"=%s', (site, user)).fetchall():
            ug.edges[r["attr"]] = Edge(
                r["weight"], r["confidence"], r["source"],
                r["last_reinforced"], r["hits"], r.get("fast", 0.0),
                r.get("salience", 0.0), r.get("provenance") or "inferred",
                int(r.get("change_count") or 0), r.get("first_seen_ts"),
                r.get("last_changed_ts"), r.get("last_change_counted_ts"))
        for r in self._q('SELECT key,value FROM user_numeric WHERE site=%s AND "user"=%s', (site, user)).fetchall():
            v = r["value"]
            try:
                v = float(v); v = int(v) if v.is_integer() else v
            except (ValueError, TypeError):
                pass
            ug.numeric[r["key"]] = v
        for r in self._q('SELECT attr,ts FROM user_history WHERE site=%s AND "user"=%s', (site, user)).fetchall():
            ug.history.setdefault(r["attr"], []).append(r["ts"])
        return ug

    def save_user(self, ug: UserGraph):
        with self._lock, self._conn.cursor() as c:
            c.execute('DELETE FROM user_edges WHERE site=%s AND "user"=%s', (ug.site, ug.user))
            c.executemany('INSERT INTO user_edges(site,"user",attr,weight,confidence,'
                          'source,last_reinforced,hits,fast,salience,provenance,'
                          'change_count,first_seen_ts,last_changed_ts,'
                          'last_change_counted_ts) '
                          'VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',
                          [(ug.site, ug.user, a, e.weight, e.confidence, e.source,
                            e.last_reinforced, e.hits, e.fast, e.salience,
                            e.provenance, e.change_count, e.first_seen_ts,
                            e.last_changed_ts, e.last_change_counted_ts)
                           for a, e in ug.edges.items()])
            c.execute('DELETE FROM user_numeric WHERE site=%s AND "user"=%s', (ug.site, ug.user))
            c.executemany('INSERT INTO user_numeric VALUES(%s,%s,%s,%s)',
                          [(ug.site, ug.user, k, str(v)) for k, v in ug.numeric.items()])
            c.execute('DELETE FROM user_history WHERE site=%s AND "user"=%s', (ug.site, ug.user))
            c.executemany('INSERT INTO user_history VALUES(%s,%s,%s,%s)',
                          [(ug.site, ug.user, a, t) for a, ts in ug.history.items() for t in ts])

    def delete_user(self, site, user):
        with self._lock:
            ids = [r["entity_id"] for r in self._q(
                'SELECT entity_id FROM entities WHERE site=%s AND "user"=%s',
                (site, user)).fetchall()]
            for entity_id in ids:
                self._q('DELETE FROM relation_facts WHERE site=%s AND "user"=%s '
                        'AND (subject_id=%s OR object_id=%s)',
                        (site, user, entity_id, entity_id))
                self._q('DELETE FROM entity_relations WHERE site=%s AND "user"=%s '
                        'AND (subject_id=%s OR object_id=%s)',
                        (site, user, entity_id, entity_id))
                self._q("DELETE FROM entity_fields WHERE entity_id=%s", (entity_id,))
                self._q('DELETE FROM entity_aliases WHERE site=%s AND "user"=%s AND entity_id=%s',
                        (site, user, entity_id))
                self._q('DELETE FROM entities WHERE site=%s AND "user"=%s AND entity_id=%s',
                        (site, user, entity_id))
            for t in ("user_edges", "user_numeric", "user_history", "events", "consents"):
                self._q(f'DELETE FROM {t} WHERE site=%s AND "user"=%s', (site, user))

    def export_user(self, site, user) -> Dict:
        ug = self.load_user(site, user)
        return {"site": site, "user": user,
                "edges": {a: e.__dict__ for a, e in ug.edges.items()},
                "numeric": ug.numeric, "events": self.recall(site, user, limit=100000),
                "consent": self.has_consent(site, user)}

    # ---- assoc ----
    def load_assoc(self, site) -> AssocGraph:
        ag = AssocGraph(site)
        for r in self._q("SELECT a,b,weight FROM assoc_edges WHERE site=%s", (site,)).fetchall():
            ag.edges[(r["a"], r["b"])] = r["weight"]
        return ag

    def save_assoc(self, ag: AssocGraph):
        with self._lock, self._conn.cursor() as c:
            c.executemany("INSERT INTO assoc_edges VALUES(%s,%s,%s,%s) "
                          "ON CONFLICT(site,a,b) DO UPDATE SET weight=EXCLUDED.weight",
                          [(ag.site, k[0], k[1], v) for k, v in ag.edges.items()])

    # ---- cabinet ----
    def append_event(self, ev: Event):
        with self._lock:
            self._q('INSERT INTO events(site,"user",ts,type,payload,attrs) VALUES(%s,%s,%s,%s,%s,%s)',
                    (ev.site, ev.user, ev.ts, ev.type, json.dumps(ev.payload), json.dumps(ev.attrs)))

    def recall(self, site, user, type=None, contains=None, limit=20) -> List[Dict]:
        q = 'SELECT ts,type,payload,attrs FROM events WHERE site=%s AND "user"=%s'
        args = [site, user]
        if type: q += " AND type=%s"; args.append(type)
        if contains: q += " AND payload LIKE %s"; args.append(f"%{contains}%")
        q += " ORDER BY ts DESC LIMIT %s"; args.append(limit)
        return [{"ts": r["ts"], "type": r["type"], "payload": json.loads(r["payload"]),
                 "attrs": json.loads(r["attrs"])} for r in self._q(q, tuple(args)).fetchall()]

    # ---- prior ----
    def load_prior(self, site) -> PopulationPrior:
        pp = PopulationPrior(site)
        for r in self._q("SELECT attr,sum,n FROM prior_node WHERE site=%s", (site,)).fetchall():
            pp._sum[r["attr"]] = r["sum"]; pp._n[r["attr"]] = r["n"]
        m = self._q("SELECT n_users FROM prior_meta WHERE site=%s", (site,)).fetchone()
        pp.n_users = m["n_users"] if m else 0
        return pp

    def save_prior(self, pp: PopulationPrior):
        with self._lock, self._conn.cursor() as c:
            c.executemany("INSERT INTO prior_node VALUES(%s,%s,%s,%s) "
                          "ON CONFLICT(site,attr) DO UPDATE SET sum=EXCLUDED.sum, n=EXCLUDED.n",
                          [(pp.site, a, pp._sum[a], pp._n[a]) for a in pp._sum])
            c.execute("INSERT INTO prior_meta VALUES(%s,%s) "
                      "ON CONFLICT(site) DO UPDATE SET n_users=EXCLUDED.n_users",
                      (pp.site, pp.n_users))

    # ---- identities + sharing ----
    def link_identity(self, person, site, local_user, ts=0.0):
        with self._lock:
            self._q("INSERT INTO identities(person,site,local_user,ts) VALUES(%s,%s,%s,%s) "
                    "ON CONFLICT DO NOTHING", (person, site, local_user, ts))

    def unlink_identity(self, person, site, local_user):
        with self._lock:
            self._q("DELETE FROM identities WHERE person=%s AND site=%s AND local_user=%s",
                    (person, site, local_user))

    def list_identities(self, person):
        return [(r["site"], r["local_user"]) for r in
                self._q("SELECT site,local_user FROM identities WHERE person=%s", (person,)).fetchall()]

    def set_share(self, person, target_site, category, allowed):
        with self._lock:
            self._q("INSERT INTO share_policy(person,target_site,category,allowed) VALUES(%s,%s,%s,%s) "
                    "ON CONFLICT(person,target_site,category) DO UPDATE SET allowed=EXCLUDED.allowed",
                    (person, target_site, category, int(allowed)))

    def get_shares(self, person, target_site):
        return {r["category"]: bool(r["allowed"]) for r in
                self._q("SELECT category,allowed FROM share_policy WHERE person=%s AND target_site=%s",
                        (person, target_site)).fetchall()}

    # ---- typed entity layer ----
    def create_entity(self, entity_id, site, user, kind, display_name, created_at):
        with self._lock:
            self._q('INSERT INTO entities(entity_id,site,"user",kind,display_name,created_at) '
                    'VALUES(%s,%s,%s,%s,%s,%s)',
                    (entity_id, site, user, kind, display_name, created_at))

    def get_entity(self, site, user, entity_id):
        row = self._q('SELECT * FROM entities WHERE site=%s AND "user"=%s AND entity_id=%s',
                      (site, user, entity_id)).fetchone()
        return dict(row) if row else None

    def entity_by_alias(self, site, user, alias_attr):
        row = self._q(
            'SELECT e.* FROM entity_aliases a JOIN entities e ON e.entity_id=a.entity_id '
            'WHERE a.site=%s AND a."user"=%s AND a.alias_attr=%s',
            (site, user, alias_attr)).fetchone()
        return dict(row) if row else None

    def link_entity_alias(self, site, user, entity_id, alias_attr,
                          source="stated", confidence=1.0):
        with self._lock:
            self._q('INSERT INTO entity_aliases(site,"user",alias_attr,entity_id,source,confidence) '
                    'VALUES(%s,%s,%s,%s,%s,%s) '
                    'ON CONFLICT(site,"user",alias_attr) DO UPDATE SET '
                    'entity_id=EXCLUDED.entity_id, source=EXCLUDED.source, confidence=EXCLUDED.confidence',
                    (site, user, alias_attr, entity_id, source, float(confidence)))

    def unlink_entity_alias(self, site, user, entity_id, alias_attr):
        with self._lock:
            self._q('DELETE FROM entity_aliases WHERE site=%s AND "user"=%s '
                    'AND entity_id=%s AND alias_attr=%s',
                    (site, user, entity_id, alias_attr))

    def list_entity_aliases(self, site, user, entity_id):
        return [dict(r) for r in self._q(
            'SELECT * FROM entity_aliases WHERE site=%s AND "user"=%s '
            'AND entity_id=%s ORDER BY alias_attr',
            (site, user, entity_id)).fetchall()]

    def set_entity_field(self, entity_id, field, value, provenance, ts):
        with self._lock:
            self._q("INSERT INTO entity_fields(entity_id,field,value,provenance,ts) "
                    "VALUES(%s,%s,%s,%s,%s) "
                    "ON CONFLICT(entity_id,field) DO UPDATE SET "
                    "value=EXCLUDED.value, provenance=EXCLUDED.provenance, ts=EXCLUDED.ts",
                    (entity_id, field, value, provenance, float(ts)))

    def list_entity_fields(self, entity_id):
        return [dict(r) for r in self._q(
            "SELECT * FROM entity_fields WHERE entity_id=%s ORDER BY field",
            (entity_id,)).fetchall()]

    def get_entity_relation(self, site, user, subject_id, relation, object_id):
        row = self._q(
            'SELECT * FROM entity_relations WHERE site=%s AND "user"=%s '
            'AND subject_id=%s AND relation=%s AND object_id=%s',
            (site, user, subject_id, relation, object_id)).fetchone()
        return dict(row) if row else None

    def upsert_entity_relation(self, row):
        with self._lock:
            self._q(
                'INSERT INTO entity_relations(site,"user",subject_id,relation,object_id,'
                'weight,confidence,hits,last_reinforced,salience,provenance,note) '
                'VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) '
                'ON CONFLICT(site,"user",subject_id,relation,object_id) DO UPDATE SET '
                'weight=EXCLUDED.weight, confidence=EXCLUDED.confidence, hits=EXCLUDED.hits, '
                'last_reinforced=EXCLUDED.last_reinforced, salience=EXCLUDED.salience, '
                'provenance=EXCLUDED.provenance, note=EXCLUDED.note',
                (row["site"], row["user"], row["subject_id"], row["relation"],
                 row["object_id"], row["weight"], row["confidence"], row["hits"],
                 row["last_reinforced"], row["salience"], row["provenance"], row["note"]))

    def list_entity_relations(self, site, user, entity_id=None):
        if entity_id is None:
            rows = self._q(
                'SELECT * FROM entity_relations WHERE site=%s AND "user"=%s '
                'ORDER BY subject_id,relation,object_id', (site, user)).fetchall()
        else:
            rows = self._q(
                'SELECT * FROM entity_relations WHERE site=%s AND "user"=%s '
                'AND (subject_id=%s OR object_id=%s) ORDER BY relation,subject_id,object_id',
                (site, user, entity_id, entity_id)).fetchall()
        return [dict(r) for r in rows]

    def get_relation_fact(self, fact_id):
        row = self._q("SELECT * FROM relation_facts WHERE fact_id=%s",
                      (fact_id,)).fetchone()
        return dict(row) if row else None

    def get_relation_fact_by_note(self, site, user, subject_id, relation, object_id, note):
        row = self._q(
            'SELECT * FROM relation_facts WHERE site=%s AND "user"=%s AND subject_id=%s '
            'AND relation=%s AND object_id=%s AND note=%s',
            (site, user, subject_id, relation, object_id, note)).fetchone()
        return dict(row) if row else None

    def upsert_relation_fact(self, row):
        with self._lock:
            existing = self.get_relation_fact_by_note(
                row["site"], row["user"], row["subject_id"], row["relation"],
                row["object_id"], row["note"])
            if existing:
                self._q(
                    "UPDATE relation_facts SET ts=%s, provenance=%s, event_id=%s "
                    "WHERE fact_id=%s",
                    (row["ts"], row["provenance"], row.get("event_id"),
                     existing["fact_id"]))
                updated = self.get_relation_fact(existing["fact_id"])
                updated["created"] = False
                return updated
            self._q(
                'INSERT INTO relation_facts(fact_id,site,"user",subject_id,relation,'
                'object_id,note,ts,provenance,event_id) '
                'VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',
                (row["fact_id"], row["site"], row["user"], row["subject_id"],
                 row["relation"], row["object_id"], row["note"], row["ts"],
                 row["provenance"], row.get("event_id")))
            created = self.get_relation_fact(row["fact_id"])
            created["created"] = True
            return created

    def list_relation_facts(self, site, user, subject_id, relation, object_id, limit=5):
        return [dict(r) for r in self._q(
            'SELECT * FROM relation_facts WHERE site=%s AND "user"=%s AND subject_id=%s '
            'AND relation=%s AND object_id=%s ORDER BY ts DESC, fact_id DESC LIMIT %s',
            (site, user, subject_id, relation, object_id, int(limit))).fetchall()]

    def delete_relation_fact(self, fact_id):
        with self._lock:
            cur = self._q("DELETE FROM relation_facts WHERE fact_id=%s", (fact_id,))
            return cur.rowcount > 0

    def delete_entity_relation(self, site, user, subject_id, relation, object_id):
        with self._lock:
            self._q('DELETE FROM relation_facts WHERE site=%s AND "user"=%s '
                    'AND subject_id=%s AND relation=%s AND object_id=%s',
                    (site, user, subject_id, relation, object_id))
            self._q('DELETE FROM entity_relations WHERE site=%s AND "user"=%s '
                    'AND subject_id=%s AND relation=%s AND object_id=%s',
                    (site, user, subject_id, relation, object_id))

    def delete_entity(self, site, user, entity_id):
        with self._lock:
            self._q('DELETE FROM relation_facts WHERE site=%s AND "user"=%s '
                    'AND (subject_id=%s OR object_id=%s)',
                    (site, user, entity_id, entity_id))
            self._q('DELETE FROM entity_relations WHERE site=%s AND "user"=%s '
                    'AND (subject_id=%s OR object_id=%s)',
                    (site, user, entity_id, entity_id))
            self._q("DELETE FROM entity_fields WHERE entity_id=%s", (entity_id,))
            self._q('DELETE FROM entity_aliases WHERE site=%s AND "user"=%s AND entity_id=%s',
                    (site, user, entity_id))
            self._q('DELETE FROM entities WHERE site=%s AND "user"=%s AND entity_id=%s',
                    (site, user, entity_id))

    def count_entity_references(self, entity_id):
        specs = [
            ("entities", "entity_id=%s", (entity_id,)),
            ("entity_aliases", "entity_id=%s", (entity_id,)),
            ("entity_fields", "entity_id=%s", (entity_id,)),
            ("entity_relations", "subject_id=%s OR object_id=%s", (entity_id, entity_id)),
            ("relation_facts", "subject_id=%s OR object_id=%s", (entity_id, entity_id)),
        ]
        total = 0
        for table, where, args in specs:
            total += self._q(f"SELECT COUNT(*) n FROM {table} WHERE {where}", args).fetchone()["n"]
        return total

    def list_users(self, site):
        return [r["user"] for r in self._q(
            'SELECT DISTINCT "user" FROM user_edges WHERE site=%s', (site,)).fetchall()]
