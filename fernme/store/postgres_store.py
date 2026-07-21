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
  PRIMARY KEY(site, "user", attr));
CREATE TABLE IF NOT EXISTS user_numeric(
  site TEXT, "user" TEXT, key TEXT, value TEXT,
  PRIMARY KEY(site, "user", key));
CREATE TABLE IF NOT EXISTS user_history(
  site TEXT, "user" TEXT, attr TEXT, ts DOUBLE PRECISION);
CREATE TABLE IF NOT EXISTS assoc_edges(
  site TEXT, a TEXT, b TEXT, weight DOUBLE PRECISION,
  users INT NOT NULL DEFAULT 0,
  PRIMARY KEY(site, a, b));
CREATE TABLE IF NOT EXISTS assoc_edge_users(
  site TEXT NOT NULL, "user" TEXT NOT NULL, a TEXT NOT NULL, b TEXT NOT NULL,
  hits INT NOT NULL DEFAULT 0,
  PRIMARY KEY(site, "user", a, b));
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
CREATE TABLE IF NOT EXISTS canonicalization_suggestions(
  suggestion_id TEXT PRIMARY KEY,
  site TEXT NOT NULL, "user" TEXT NOT NULL,
  kind TEXT NOT NULL, payload TEXT NOT NULL, score DOUBLE PRECISION NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending',
  created_ts DOUBLE PRECISION NOT NULL, decided_ts DOUBLE PRECISION);
CREATE TABLE IF NOT EXISTS assets(
  id TEXT PRIMARY KEY, site TEXT NOT NULL, "user" TEXT NOT NULL,
  type TEXT NOT NULL, mime TEXT NOT NULL, uri TEXT NOT NULL,
  sha256 TEXT NOT NULL, bytes BIGINT NOT NULL, created_ts DOUBLE PRECISION NOT NULL,
  source TEXT NOT NULL, thumbnail_uri TEXT NOT NULL,
  exif_stripped INT NOT NULL, sensitive INT NOT NULL,
  consent INT NOT NULL, status TEXT NOT NULL DEFAULT 'active');
CREATE INDEX IF NOT EXISTS idx_events_user ON events(site, "user", ts);
CREATE INDEX IF NOT EXISTS idx_hist_user ON user_history(site, "user", attr);
CREATE INDEX IF NOT EXISTS idx_assoc_edge_users_edge
  ON assoc_edge_users(site, a, b);
CREATE INDEX IF NOT EXISTS idx_relation_facts_relation
  ON relation_facts(site, "user", subject_id, relation, object_id, ts);
CREATE INDEX IF NOT EXISTS idx_canonicalization_suggestions_user
  ON canonicalization_suggestions(site, "user", status, created_ts);
CREATE INDEX IF NOT EXISTS idx_assets_owner_status
  ON assets(site, "user", status, created_ts);
CREATE UNIQUE INDEX IF NOT EXISTS idx_assets_owner_sha_active
  ON assets(site, "user", sha256) WHERE status='active';
"""


class PostgresStore:
    def __init__(self, dsn: str):
        self.dsn = dsn
        self._lock = threading.Lock()
        self._conn = psycopg.connect(dsn, autocommit=True, row_factory=dict_row)
        self._conn.execute(SCHEMA)
        for col in ("fast", "salience"):   # forward-compat for DBs created before these columns
            self._conn.execute("ALTER TABLE user_edges ADD COLUMN IF NOT EXISTS %s DOUBLE PRECISION DEFAULT 0" % col)
        self._conn.execute(
            "ALTER TABLE user_edges ADD COLUMN IF NOT EXISTS provenance TEXT NOT NULL DEFAULT 'inferred'"
        )
        self._conn.execute(
            "ALTER TABLE assoc_edges ADD COLUMN IF NOT EXISTS users INT NOT NULL DEFAULT 0"
        )
        self._backfill_assoc_contributors()

    def _q(self, sql, args=()):
        return self._conn.execute(sql, args)

    @staticmethod
    def _assoc_key(a, b):
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
                out.append(PostgresStore._assoc_key(names[i], names[j]))
        return out

    def _refresh_assoc_user_counts(self, site, pairs=None, delete_empty=False):
        pairs = list(dict.fromkeys(pairs or []))
        if not pairs:
            return
        for a, b in pairs:
            count = self._q(
                'SELECT COUNT(*) n FROM assoc_edge_users WHERE site=%s AND a=%s AND b=%s',
                (site, a, b)).fetchone()["n"]
            if delete_empty and count == 0:
                self._q(
                    "DELETE FROM assoc_edges WHERE site=%s AND a=%s AND b=%s",
                    (site, a, b))
            else:
                self._q(
                    "UPDATE assoc_edges SET users=%s WHERE site=%s AND a=%s AND b=%s",
                    (int(count), site, a, b))

    def _backfill_assoc_contributors(self):
        existing = self._q("SELECT COUNT(*) n FROM assoc_edge_users").fetchone()["n"]
        if existing:
            return
        pairs_by_site = {}
        for r in self._q('SELECT site,"user",attrs FROM events').fetchall():
            try:
                attrs = json.loads(r["attrs"])
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
            for a, b in self._pairs_from_attrs(attrs):
                pairs_by_site.setdefault(r["site"], set()).add((a, b))
                self._q(
                    'INSERT INTO assoc_edge_users(site,"user",a,b,hits) '
                    'VALUES(%s,%s,%s,%s,1) '
                    'ON CONFLICT(site,"user",a,b) DO UPDATE SET hits=assoc_edge_users.hits+1',
                    (r["site"], r["user"], a, b))
        for site, pairs in pairs_by_site.items():
            self._refresh_assoc_user_counts(site, pairs)

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
            ug.edges[r["attr"]] = Edge(r["weight"], r["confidence"], r["source"],
                                       r["last_reinforced"], r["hits"], r.get("fast", 0.0),
                                       r.get("salience", 0.0), r.get("provenance", "inferred"))
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
            c.executemany('INSERT INTO user_edges VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',
                          [(ug.site, ug.user, a, e.weight, e.confidence, e.source,
                            e.last_reinforced, e.hits, e.fast, e.salience, e.provenance)
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
            assoc_pairs = [
                (r["a"], r["b"]) for r in self._q(
                    'SELECT a,b FROM assoc_edge_users WHERE site=%s AND "user"=%s',
                    (site, user)).fetchall()
            ]
            self._q('DELETE FROM assoc_edge_users WHERE site=%s AND "user"=%s',
                    (site, user))
            self._refresh_assoc_user_counts(site, assoc_pairs, delete_empty=True)
            for t in ("user_edges", "user_numeric", "user_history", "events", "consents"):
                self._q(f'DELETE FROM {t} WHERE site=%s AND "user"=%s', (site, user))
            self._q('DELETE FROM canonicalization_suggestions WHERE site=%s AND "user"=%s',
                    (site, user))
            self._q('DELETE FROM assets WHERE site=%s AND "user"=%s', (site, user))

    def export_user(self, site, user) -> Dict:
        ug = self.load_user(site, user)
        return {"site": site, "user": user,
                "edges": {a: e.__dict__ for a, e in ug.edges.items()},
                "numeric": ug.numeric, "events": self.recall(site, user, limit=100000),
                "consent": self.has_consent(site, user)}

    # ---- assoc ----
    def load_assoc(self, site, user=None, min_users=1) -> AssocGraph:
        ag = AssocGraph(site)
        min_users = int(min_users or 1)
        if min_users <= 1:
            rows = self._q(
                "SELECT a,b,weight FROM assoc_edges WHERE site=%s", (site,)).fetchall()
        elif user is None:
            rows = self._q(
                "SELECT a,b,weight FROM assoc_edges WHERE site=%s AND users>=%s",
                (site, min_users)).fetchall()
        else:
            rows = self._q(
                "SELECT e.a,e.b,e.weight FROM assoc_edges e "
                "LEFT JOIN assoc_edge_users u ON u.site=e.site AND u.a=e.a "
                'AND u.b=e.b AND u."user"=%s '
                "WHERE e.site=%s AND (e.users>=%s OR u.\"user\" IS NOT NULL)",
                (user, site, min_users)).fetchall()
        for r in rows:
            ag.edges[(r["a"], r["b"])] = r["weight"]
        return ag

    def save_assoc(self, ag: AssocGraph, contributor_user=None, touched_pairs=None):
        touched_pairs = [self._assoc_key(a, b) for a, b in (touched_pairs or [])]
        with self._lock, self._conn.cursor() as c:
            c.executemany("INSERT INTO assoc_edges(site,a,b,weight) VALUES(%s,%s,%s,%s) "
                          "ON CONFLICT(site,a,b) DO UPDATE SET weight=EXCLUDED.weight",
                          [(ag.site, k[0], k[1], v) for k, v in ag.edges.items()])
            if contributor_user and touched_pairs:
                c.executemany(
                    'INSERT INTO assoc_edge_users(site,"user",a,b,hits) '
                    'VALUES(%s,%s,%s,%s,1) '
                    'ON CONFLICT(site,"user",a,b) DO UPDATE SET hits=assoc_edge_users.hits+1',
                    [(ag.site, contributor_user, a, b) for a, b in touched_pairs])
                self._refresh_assoc_user_counts(ag.site, touched_pairs)

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

    def events_chronological(self, site, user) -> List[Dict]:
        rows = self._q(
            'SELECT id,ts,type,payload,attrs FROM events '
            'WHERE site=%s AND "user"=%s ORDER BY id ASC',
            (site, user),
        ).fetchall()
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

    def delete_document_artifacts(self, site, user, source_sha256) -> Dict:
        with self._lock:
            event_rows = self._q(
                'SELECT id,ts,type,payload,attrs FROM events '
                'WHERE site=%s AND "user"=%s AND type=%s ORDER BY id ASC',
                (site, user, "document"),
            ).fetchall()
            removed = []
            for row in event_rows:
                payload = json.loads(row["payload"])
                if payload.get("source_sha256") != source_sha256:
                    continue
                removed.append({
                    "id": row["id"],
                    "ts": row["ts"],
                    "type": row["type"],
                    "payload": payload,
                    "attrs": json.loads(row["attrs"]),
                })

            suggestion_rows = self._q(
                'SELECT suggestion_id,payload FROM canonicalization_suggestions '
                'WHERE site=%s AND "user"=%s',
                (site, user),
            ).fetchall()
            suggestion_ids = [
                row["suggestion_id"]
                for row in suggestion_rows
                if json.loads(row["payload"]).get("source_sha256") == source_sha256
            ]
            with self._conn.cursor() as cursor:
                if removed:
                    cursor.executemany(
                        "DELETE FROM events WHERE id=%s",
                        [(row["id"],) for row in removed],
                    )
                if suggestion_ids:
                    cursor.executemany(
                        "DELETE FROM canonicalization_suggestions WHERE suggestion_id=%s",
                        [(suggestion_id,) for suggestion_id in suggestion_ids],
                    )
        return {"events": removed, "suggestions_deleted": len(suggestion_ids)}

    # ---- local media asset metadata (bytes remain in the blob store) ----
    @staticmethod
    def _asset_row(row):
        if row is None:
            return None
        out = dict(row)
        for key in ("exif_stripped", "sensitive", "consent"):
            out[key] = bool(out[key])
        return out

    def insert_asset(self, row):
        with self._lock:
            self._q(
                'INSERT INTO assets(id,site,"user",type,mime,uri,sha256,bytes,'
                'created_ts,source,thumbnail_uri,exif_stripped,sensitive,consent,status) '
                'VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',
                (row["id"], row["site"], row["user"], row["type"], row["mime"],
                 row["uri"], row["sha256"], int(row["bytes"]), row["created_ts"],
                 row["source"], row["thumbnail_uri"], int(row["exif_stripped"]),
                 int(row["sensitive"]), int(row["consent"]), row["status"]),
            )
        return self.get_asset(row["site"], row["user"], row["id"])

    def get_asset(self, site, user, asset_id_or_sha256, status="active"):
        row = self._q(
            'SELECT * FROM assets WHERE site=%s AND "user"=%s AND status=%s '
            'AND (id=%s OR sha256=%s) ORDER BY created_ts DESC LIMIT 1',
            (site, user, status, asset_id_or_sha256, asset_id_or_sha256),
        ).fetchone()
        return self._asset_row(row)

    def list_assets(self, site, user, status="active", limit=100):
        rows = self._q(
            'SELECT * FROM assets WHERE site=%s AND "user"=%s AND status=%s '
            'ORDER BY created_ts DESC,id ASC LIMIT %s',
            (site, user, status, int(limit)),
        ).fetchall()
        return [self._asset_row(row) for row in rows]

    def set_asset_sensitive(self, site, user, asset_id, sensitive):
        with self._lock:
            self._q(
                'UPDATE assets SET sensitive=%s WHERE site=%s AND "user"=%s '
                "AND id=%s AND status='active'",
                (int(sensitive), site, user, asset_id),
            )
        return self.get_asset(site, user, asset_id)

    def delete_asset_row(self, site, user, asset_id):
        with self._lock:
            self._q(
                'DELETE FROM assets WHERE site=%s AND "user"=%s AND id=%s',
                (site, user, asset_id),
            )

    def delete_asset_artifacts(self, site, user, asset_id, source_sha256):
        with self._lock:
            event_rows = self._q(
                'SELECT id,ts,type,payload,attrs FROM events '
                'WHERE site=%s AND "user"=%s AND type=%s ORDER BY id ASC',
                (site, user, "asset"),
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
            suggestion_rows = self._q(
                'SELECT suggestion_id,payload FROM canonicalization_suggestions '
                'WHERE site=%s AND "user"=%s', (site, user)).fetchall()
            suggestion_ids = []
            for row in suggestion_rows:
                payload = json.loads(row["payload"])
                if (payload.get("asset_id") == asset_id or
                        payload.get("source_sha256") == source_sha256):
                    suggestion_ids.append(row["suggestion_id"])
            with self._conn.cursor() as cursor:
                if removed:
                    cursor.executemany(
                        "DELETE FROM events WHERE id=%s",
                        [(row["id"],) for row in removed])
                if suggestion_ids:
                    cursor.executemany(
                        "DELETE FROM canonicalization_suggestions WHERE suggestion_id=%s",
                        [(suggestion_id,) for suggestion_id in suggestion_ids])
                cursor.execute(
                    "UPDATE assets SET status='tombstoned',uri='',thumbnail_uri='' "
                    'WHERE site=%s AND "user"=%s AND id=%s',
                    (site, user, asset_id),
                )
        return {"events": removed, "suggestions_deleted": len(suggestion_ids)}

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

    def list_entities(self, site, user):
        return [dict(r) for r in self._q(
            'SELECT * FROM entities WHERE site=%s AND "user"=%s '
            'ORDER BY display_name,entity_id',
            (site, user)).fetchall()]

    def update_entity_kind(self, site, user, entity_id, kind):
        with self._lock:
            self._q(
                'UPDATE entities SET kind=%s WHERE site=%s AND "user"=%s AND entity_id=%s',
                (kind, site, user, entity_id))

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
            self._q('DELETE FROM canonicalization_suggestions WHERE site=%s AND "user"=%s '
                    'AND (payload LIKE %s OR payload LIKE %s OR payload LIKE %s)',
                    (site, user, f'%"entity_id":"{entity_id}"%',
                     f'%"subject_id":"{entity_id}"%', f'%"object_id":"{entity_id}"%'))

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

    # ---- suggest-and-approve canonicalization queue ----
    @staticmethod
    def _suggestion_row(row):
        out = dict(row)
        out["payload"] = json.loads(out["payload"])
        return out

    def upsert_suggestion(self, row):
        payload = json.dumps(row["payload"], sort_keys=True, separators=(",", ":"))
        with self._lock:
            existing = self._q(
                "SELECT status FROM canonicalization_suggestions WHERE suggestion_id=%s",
                (row["suggestion_id"],)).fetchone()
            if existing:
                if existing["status"] == "pending":
                    self._q(
                        "UPDATE canonicalization_suggestions SET payload=%s, score=%s "
                        "WHERE suggestion_id=%s",
                        (payload, float(row["score"]), row["suggestion_id"]))
                return self.get_suggestion(row["suggestion_id"])
            self._q(
                'INSERT INTO canonicalization_suggestions('
                'suggestion_id,site,"user",kind,payload,score,status,created_ts,decided_ts) '
                'VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)',
                (row["suggestion_id"], row["site"], row["user"], row["kind"],
                 payload, float(row["score"]), row["status"], float(row["created_ts"]),
                 row.get("decided_ts")))
            return self.get_suggestion(row["suggestion_id"])

    def get_suggestion(self, suggestion_id):
        row = self._q(
            "SELECT * FROM canonicalization_suggestions WHERE suggestion_id=%s",
            (suggestion_id,)).fetchone()
        return self._suggestion_row(row) if row else None

    def list_suggestions(self, site, user, status=None):
        q = 'SELECT * FROM canonicalization_suggestions WHERE site=%s AND "user"=%s'
        args = [site, user]
        if status:
            q += " AND status=%s"
            args.append(status)
        q += " ORDER BY score DESC, created_ts ASC, suggestion_id ASC"
        return [self._suggestion_row(r) for r in self._q(q, tuple(args)).fetchall()]

    def decide_suggestion(self, suggestion_id, status, decided_ts):
        with self._lock:
            self._q(
                "UPDATE canonicalization_suggestions SET status=%s, decided_ts=%s "
                "WHERE suggestion_id=%s",
                (status, float(decided_ts), suggestion_id))
        return self.get_suggestion(suggestion_id)

    def purge_expired_suggestions(self, site, user, now, ttl_days):
        cutoff = float(now) - float(ttl_days)
        with self._lock:
            cur = self._q(
                'DELETE FROM canonicalization_suggestions WHERE site=%s AND "user"=%s '
                "AND status='pending' AND created_ts<%s",
                (site, user, cutoff))
            return cur.rowcount

    def trim_pending_suggestions(self, site, user, cap):
        pending = self.list_suggestions(site, user, "pending")
        if len(pending) <= cap:
            return 0
        drop = pending[int(cap):]
        with self._lock:
            with self._conn.cursor() as c:
                c.executemany(
                    "DELETE FROM canonicalization_suggestions WHERE suggestion_id=%s",
                    [(row["suggestion_id"],) for row in drop])
        return len(drop)

    def delete_suggestions_for_entity(self, site, user, entity_id):
        with self._lock:
            cur = self._q(
                'DELETE FROM canonicalization_suggestions WHERE site=%s AND "user"=%s '
                'AND (payload LIKE %s OR payload LIKE %s OR payload LIKE %s)',
                (site, user, f'%"entity_id":"{entity_id}"%',
                 f'%"subject_id":"{entity_id}"%', f'%"object_id":"{entity_id}"%'))
            return cur.rowcount

    def list_users(self, site):
        return [r["user"] for r in self._q(
            'SELECT DISTINCT "user" FROM user_edges WHERE site=%s', (site,)).fetchall()]
