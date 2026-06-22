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
  source TEXT, last_reinforced DOUBLE PRECISION, hits INT, fast DOUBLE PRECISION DEFAULT 0, salience DOUBLE PRECISION DEFAULT 0,
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
CREATE INDEX IF NOT EXISTS idx_events_user ON events(site, "user", ts);
CREATE INDEX IF NOT EXISTS idx_hist_user ON user_history(site, "user", attr);
"""


class PostgresStore:
    def __init__(self, dsn: str):
        self.dsn = dsn
        self._lock = threading.Lock()
        self._conn = psycopg.connect(dsn, autocommit=True, row_factory=dict_row)
        self._conn.execute(SCHEMA)
        for col in ("fast", "salience"):   # forward-compat for DBs created before these columns
            self._conn.execute("ALTER TABLE user_edges ADD COLUMN IF NOT EXISTS %s DOUBLE PRECISION DEFAULT 0" % col)

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
            ug.edges[r["attr"]] = Edge(r["weight"], r["confidence"], r["source"],
                                       r["last_reinforced"], r["hits"], r.get("fast", 0.0), r.get("salience", 0.0))
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
            c.executemany('INSERT INTO user_edges VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',
                          [(ug.site, ug.user, a, e.weight, e.confidence, e.source,
                            e.last_reinforced, e.hits, e.fast, e.salience) for a, e in ug.edges.items()])
            c.execute('DELETE FROM user_numeric WHERE site=%s AND "user"=%s', (ug.site, ug.user))
            c.executemany('INSERT INTO user_numeric VALUES(%s,%s,%s,%s)',
                          [(ug.site, ug.user, k, str(v)) for k, v in ug.numeric.items()])
            c.execute('DELETE FROM user_history WHERE site=%s AND "user"=%s', (ug.site, ug.user))
            c.executemany('INSERT INTO user_history VALUES(%s,%s,%s,%s)',
                          [(ug.site, ug.user, a, t) for a, ts in ug.history.items() for t in ts])

    def delete_user(self, site, user):
        with self._lock:
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

    def list_users(self, site):
        return [r["user"] for r in self._q(
            'SELECT DISTINCT "user" FROM user_edges WHERE site=%s', (site,)).fetchall()]
