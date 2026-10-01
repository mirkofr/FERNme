"""Postgres-backed store for FERNme — same interface as SQLiteStore, for
server deployments. Tested against a real Postgres 16 instance (see
tests/test_postgres.py, which uses the rootless `pgserver`).

Zero-config use is unchanged: ``PostgresStore(dsn)`` opens one connection and
creates its tables in the default schema. For embedding in a host application:

* ``schema="fernme"`` keeps every table in its own schema;
* ``pool_size=(1, 10)`` uses a connection pool (``psycopg-pool``), or
  ``pool=<host psycopg_pool.ConnectionPool>`` borrows the host's pool;
* ``auto_migrate=False`` skips DDL at startup and only checks the schema
  version; the host runs ``fernme-migrate --dsn ... --schema ...`` (or
  ``PostgresStore.migrate_database(dsn, schema)``) in its own migration step.

Each operation runs on one connection: the single connection under a lock, or
a pooled connection per thread. Multi-statement writes run in a transaction,
and service writes take transaction-scoped advisory locks per (site, user) and
per site, so separate processes and servers do not lose updates.

Note: `user` is reserved in Postgres, so it is quoted everywhere."""
from __future__ import annotations
import json, re, threading
from contextlib import contextmanager
from typing import List, Optional, Dict
import psycopg
from psycopg.rows import dict_row
from ..audit import entry_hash, GENESIS
from ..core.graph import UserGraph, AssocGraph, Edge, Event
from ..prior.population import PopulationPrior

# Bump when SCHEMA or the migration steps in _migrate_unlocked change.
SCHEMA_VERSION = 2
_SCHEMA_NAME_RE = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")

SCHEMA = """
CREATE TABLE IF NOT EXISTS consents(
  site TEXT, "user" TEXT, granted INT, ts DOUBLE PRECISION,
  PRIMARY KEY(site, "user"));
CREATE TABLE IF NOT EXISTS consent_requests(
  site TEXT NOT NULL, "user" TEXT NOT NULL, requested_by TEXT NOT NULL DEFAULT '',
  requested_ts DOUBLE PRECISION NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
  decided_ts DOUBLE PRECISION, PRIMARY KEY(site, "user"));
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
CREATE TABLE IF NOT EXISTS documents(
  document_id TEXT PRIMARY KEY, site TEXT NOT NULL, "user" TEXT NOT NULL,
  source_sha256 TEXT NOT NULL, source_name TEXT NOT NULL,
  markdown_path TEXT NOT NULL, envelope_path TEXT NOT NULL,
  mime_type TEXT NOT NULL, extraction_quality TEXT NOT NULL,
  warning_count INT NOT NULL, block_count INT NOT NULL,
  created_ts DOUBLE PRECISION NOT NULL, imported_ts DOUBLE PRECISION NOT NULL,
  status TEXT NOT NULL DEFAULT 'active', pinned INT NOT NULL DEFAULT 0,
  authoritative INT NOT NULL DEFAULT 0, superseded_by TEXT NOT NULL DEFAULT '',
  UNIQUE(site, "user", source_sha256));
CREATE TABLE IF NOT EXISTS document_tags(
  document_id TEXT NOT NULL, site TEXT NOT NULL, "user" TEXT NOT NULL,
  tag TEXT NOT NULL, provenance TEXT NOT NULL DEFAULT 'human_approved',
  suggestion_id TEXT NOT NULL DEFAULT '', approved_ts DOUBLE PRECISION NOT NULL,
  PRIMARY KEY(document_id, tag));
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
CREATE INDEX IF NOT EXISTS idx_assoc_edges_b ON assoc_edges(site, b);
CREATE INDEX IF NOT EXISTS idx_documents_owner_status
  ON documents(site, "user", status, pinned, imported_ts);
CREATE INDEX IF NOT EXISTS idx_document_tags_owner_tag
  ON document_tags(site, "user", tag, document_id);
CREATE INDEX IF NOT EXISTS idx_assets_owner_status
  ON assets(site, "user", status, created_ts);
CREATE UNIQUE INDEX IF NOT EXISTS idx_assets_owner_sha_active
  ON assets(site, "user", sha256) WHERE status='active';
CREATE TABLE IF NOT EXISTS audit(
  site TEXT, "user" TEXT, seq INT, ts DOUBLE PRECISION, action TEXT, detail TEXT,
  prev_hash TEXT, hash TEXT, PRIMARY KEY(site, "user", seq));
CREATE TABLE IF NOT EXISTS settings(
  site TEXT NOT NULL, "user" TEXT NOT NULL, key TEXT NOT NULL, value TEXT NOT NULL,
  text TEXT NOT NULL DEFAULT '', ts DOUBLE PRECISION NOT NULL DEFAULT 0,
  PRIMARY KEY(site, "user", key));
CREATE TABLE IF NOT EXISTS site_policy(
  site TEXT NOT NULL, key TEXT NOT NULL, value TEXT NOT NULL,
  PRIMARY KEY(site, key));
CREATE TABLE IF NOT EXISTS fernme_secret(
  id INT PRIMARY KEY, key_hex TEXT NOT NULL, audit_legacy BOOLEAN NOT NULL);
CREATE TABLE IF NOT EXISTS fernme_schema_version(
  id INT PRIMARY KEY, version INT NOT NULL);
"""


class _Result:
    """Fetched rows of one statement, so a pooled connection can go back to the
    pool before the caller reads them (cursor-like: fetchone/fetchall/rowcount)."""
    __slots__ = ("_rows", "rowcount", "_i")

    def __init__(self, cur):
        self._rows = cur.fetchall() if cur.description is not None else []
        self.rowcount = cur.rowcount
        self._i = 0

    def fetchone(self):
        if self._i >= len(self._rows):
            return None
        self._i += 1
        return self._rows[self._i - 1]

    def fetchall(self):
        rows, self._i = self._rows[self._i:], len(self._rows)
        return rows

    def __iter__(self):
        return iter(self.fetchall())


class SchemaVersionError(RuntimeError):
    """The database schema is missing or older than this FERNme version needs."""


class PostgresStore:
    def __init__(self, dsn: str = None, *, schema: str = None, pool=None,
                 pool_size=None, auto_migrate: bool = True):
        """``dsn``: libpq connection string. ``schema``: put FERNme's tables in
        this schema (default: the connection's search_path, as before).
        ``pool``: a host ``psycopg_pool.ConnectionPool`` to borrow connections
        from; ``pool_size=(min, max)``: create a dedicated pool from ``dsn``.
        Without either, one connection is shared under a lock (the default).
        ``auto_migrate=False``: run no DDL here; require the schema version
        created by ``fernme-migrate``."""
        if schema is not None and not _SCHEMA_NAME_RE.match(schema):
            raise ValueError("schema: lowercase letters, digits and '_' (max 63)")
        if pool is not None and pool_size is not None:
            raise ValueError("pass either pool or pool_size, not both")
        if dsn is None and pool is None:
            raise ValueError("PostgresStore needs a dsn or a pool")
        self.dsn = dsn
        self.schema = schema
        self._lock = threading.RLock()        # serializes the single connection
        self._local = threading.local()       # per-thread pooled connection
        self._single = None
        self._pool = None
        self._own_pool = False
        if pool is not None:
            self._pool = pool
        elif pool_size is not None:
            self._pool = self.create_pool(dsn, schema=schema, pool_size=pool_size)
            self._own_pool = True
        else:
            self._single = psycopg.connect(dsn, autocommit=True, row_factory=dict_row)
            if schema:                        # the schema itself is created by migrate()
                self._single.execute("SELECT set_config('search_path', %s, false)",
                                     (self._search_path(),))
        try:
            if auto_migrate:
                self.migrate()
            else:
                self.check_schema()
        except BaseException:
            self.close()                      # do not leak the connection or our pool
            raise

    # ---- connections ----
    @staticmethod
    def create_pool(dsn: str, schema: str = None, pool_size=(1, 10), **pool_kwargs):
        """A ``psycopg_pool.ConnectionPool`` configured for FERNme (autocommit,
        dict rows, ``search_path`` set to ``schema``). Needs ``psycopg-pool``
        (``pip install "fernme[postgres]"``)."""
        try:
            from psycopg_pool import ConnectionPool
        except ImportError as exc:                       # pragma: no cover
            raise ImportError('pooling needs psycopg-pool: pip install "fernme[postgres]"') from exc
        if schema is not None and not _SCHEMA_NAME_RE.match(schema):
            raise ValueError("schema: lowercase letters, digits and '_' (max 63)")
        lo, hi = (pool_size, pool_size) if isinstance(pool_size, int) else pool_size
        path = f'"{schema}"' if schema else None

        def configure(conn):
            conn.autocommit = True
            conn.row_factory = dict_row
            if path:
                conn.execute("SELECT set_config('search_path', %s, false)", (path,))
        pool_kwargs.setdefault("open", True)
        return ConnectionPool(dsn, min_size=int(lo), max_size=int(hi),
                              configure=configure, **pool_kwargs)

    def close(self):
        if self._single is not None:
            self._single.close()
        elif self._own_pool:
            self._pool.close()

    def _search_path(self) -> str:
        # Only FERNme's schema (pg_catalog is always searched): a missing table
        # must fail, never resolve to a same-named table in public.
        return f'"{self.schema}"'

    @property
    def _conn(self):
        if self._single is not None:
            return self._single
        conn = getattr(self._local, "conn", None)
        if conn is None:
            raise RuntimeError("PostgresStore: no pooled connection outside a session")
        return conn

    @contextmanager
    def _session(self):
        """One connection for the duration of an operation (re-entrant)."""
        if self._single is not None:
            with self._lock:
                yield self._single
            return
        depth = getattr(self._local, "depth", 0)
        if depth:
            self._local.depth = depth + 1
            try:
                yield self._local.conn
            finally:
                self._local.depth -= 1
            return
        with self._pool.connection() as conn:
            restore = self._borrow(conn)
            self._local.conn, self._local.depth = conn, 1
            try:
                yield conn
            finally:
                self._local.conn, self._local.depth = None, 0
                self._give_back(conn, restore)

    def _borrow(self, conn):
        """Make a host-pool connection fit FERNme; return what to restore. A pool
        made by create_pool() is already configured, so this costs nothing."""
        if self._own_pool:
            return None
        restore = {"autocommit": conn.autocommit, "row_factory": conn.row_factory}
        if not conn.autocommit:
            conn.autocommit = True
        conn.row_factory = dict_row
        if self.schema:
            row = conn.execute(
                "SELECT current_setting('search_path') AS old, "
                "set_config('search_path', %s, false)", (self._search_path(),)).fetchone()
            restore["search_path"] = row["old"]
        return restore

    @staticmethod
    def _give_back(conn, restore):
        if not restore or conn.closed:
            return
        try:
            if "search_path" in restore:
                conn.execute("SELECT set_config('search_path', %s, false)",
                             (restore["search_path"],))
            conn.row_factory = restore["row_factory"]
            conn.autocommit = restore["autocommit"]
        except psycopg.Error:
            pass                              # the pool discards broken connections

    # ---- schema / migrations ----
    # How long a migration waits for a table lock held by live traffic before it
    # gives up (and can simply be retried), instead of stalling writers.
    MIGRATION_LOCK_TIMEOUT = "30s"

    def migrate(self):
        """Create or upgrade FERNme's tables. Idempotent, and a no-op without any
        DDL or table lock when the schema is already current, so restarting
        servers never block live traffic. Concurrent runs (several processes or
        deploy jobs) serialize on an advisory lock taken before any DDL."""
        if self.schema_version() >= SCHEMA_VERSION:
            return SCHEMA_VERSION
        with self._session() as conn, conn.transaction():
            conn.execute("SELECT pg_advisory_xact_lock(hashtext(%s))",
                         (f"fernme:migrate:{self.schema or ''}",))
            conn.execute("SELECT set_config('lock_timeout', %s, true)",
                         (self.MIGRATION_LOCK_TIMEOUT,))
            if self.schema:
                conn.execute(f'CREATE SCHEMA IF NOT EXISTS "{self.schema}"')
            if self._schema_version_unlocked(conn) < SCHEMA_VERSION:   # lost the race? done
                self._migrate_unlocked(conn)
        return SCHEMA_VERSION

    def _missing_column(self, conn, table, column) -> bool:
        return conn.execute(
            "SELECT 1 FROM information_schema.columns WHERE table_schema=current_schema() "
            "AND table_name=%s AND column_name=%s", (table, column)).fetchone() is None

    def _migrate_unlocked(self, conn):
        conn.execute(SCHEMA)
        # Forward-compat for databases created before these columns; ALTER only
        # when needed (ALTER takes an exclusive lock even with IF NOT EXISTS).
        for col in ("fast", "salience"):
            if self._missing_column(conn, "user_edges", col):
                conn.execute("ALTER TABLE user_edges ADD COLUMN %s DOUBLE PRECISION DEFAULT 0" % col)
        if self._missing_column(conn, "user_edges", "provenance"):
            conn.execute("ALTER TABLE user_edges ADD COLUMN provenance TEXT NOT NULL "
                         "DEFAULT 'inferred'")
        if self._missing_column(conn, "assoc_edges", "users"):
            conn.execute("ALTER TABLE assoc_edges ADD COLUMN users INT NOT NULL DEFAULT 0")
        self._backfill_assoc_contributors()      # once, while upgrading
        conn.execute(
            "INSERT INTO fernme_schema_version(id, version) VALUES(1, %s) "
            "ON CONFLICT(id) DO UPDATE SET version=GREATEST(fernme_schema_version.version, "
            "EXCLUDED.version)", (SCHEMA_VERSION,))

    def _schema_version_unlocked(self, conn) -> int:
        table = (f'"{self.schema}".fernme_schema_version' if self.schema
                 else "fernme_schema_version")
        if not conn.execute("SELECT to_regclass(%s) IS NOT NULL AS ok",
                            (table,)).fetchone()["ok"]:
            return 0
        row = conn.execute(f"SELECT version FROM {table} WHERE id=1").fetchone()
        return int(row["version"]) if row else 0

    def schema_version(self) -> int:
        with self._session() as conn:
            return self._schema_version_unlocked(conn)

    def check_schema(self):
        found = self.schema_version()
        if found < SCHEMA_VERSION:
            where = f" in schema '{self.schema}'" if self.schema else ""
            raise SchemaVersionError(
                f"FERNme needs database schema version {SCHEMA_VERSION}{where}, found "
                f"{found or 'none'}. Run: fernme-migrate --dsn <dsn>"
                + (f" --schema {self.schema}" if self.schema else ""))
        return found

    @classmethod
    def migrate_database(cls, dsn: str, schema: str = None) -> int:
        """Run FERNme's migrations once (for a host app's migration step)."""
        store = cls(dsn, schema=schema, auto_migrate=True)
        try:
            return store.schema_version()
        finally:
            store.close()

    # ---- locking ----
    def _lock_name(self, *parts) -> str:
        if self.schema:
            return ":".join(("fernme", self.schema) + parts)
        return ":".join(("fernme",) + parts)

    @contextmanager
    def transaction(self, lock_key: str = None, user_key: str = None,
                    site_lock: bool = True):
        """Atomic, serialized read-modify-write across store calls. Nested use
        (including the per-method transactions below) becomes a savepoint.

        Transaction-scoped advisory locks serialize other threads, processes and
        servers: first the (site, user) lock when ``user_key`` is given, then the
        site lock (``site_lock``) for writes that touch site-shared rows (the
        association graph, the prior). Always in that order, so no deadlock."""
        with self._session() as conn, conn.transaction():
            if user_key is not None:
                conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                             (self._lock_name(lock_key or "*", "user", str(user_key)),))
            if site_lock or user_key is None:
                conn.execute("SELECT pg_advisory_xact_lock(hashtext(%s))",
                             (self._lock_name(lock_key or "*"),))
            yield self

    def _q(self, sql, args=()):
        with self._session() as conn:
            return _Result(conn.execute(sql, args))

    def load_or_create_secret(self):
        """Per-deployment secret shared by every process on this database, for
        deployments that do not set FERNME_SECRET_KEY. Returns (hex, audit_legacy)."""
        import secrets as _secrets
        with self._session(), self._conn.transaction():
            self._conn.execute("SELECT pg_advisory_xact_lock(hashtext(%s))",
                               (self._lock_name("secret"),))
            row = self._conn.execute(
                "SELECT key_hex, audit_legacy FROM fernme_secret WHERE id=1").fetchone()
            if row:
                return row["key_hex"], bool(row["audit_legacy"])
            # Postgres never had chains signed with the legacy public key (older
            # versions had no Postgres audit table), so a new secret is never
            # legacy: rows that exist were signed with an explicit or env key.
            legacy = False
            key_hex = _secrets.token_hex(32)
            self._conn.execute(
                "INSERT INTO fernme_secret(id, key_hex, audit_legacy) VALUES(1,%s,%s)",
                (key_hex, legacy))
            return key_hex, legacy

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
        with self._session():
            self._q('INSERT INTO consents(site,"user",granted,ts) VALUES(%s,%s,%s,%s) '
                    'ON CONFLICT(site,"user") DO UPDATE SET granted=EXCLUDED.granted, ts=EXCLUDED.ts',
                    (site, user, int(granted), ts))

    def has_consent(self, site, user) -> bool:
        r = self._q('SELECT granted FROM consents WHERE site=%s AND "user"=%s', (site, user)).fetchone()
        return bool(r["granted"]) if r else False

    # ---- consent requests (the memory inbox) ----
    def upsert_consent_request(self, site, user, requested_by, ts, reopen_denied=True):
        keep = "" if reopen_denied else " WHERE consent_requests.status <> 'denied'"
        with self._session():
            self._q('INSERT INTO consent_requests(site,"user",requested_by,requested_ts,status) '
                    "VALUES(%s,%s,%s,%s,'pending') ON CONFLICT(site,\"user\") DO UPDATE SET "
                    "requested_by=EXCLUDED.requested_by, requested_ts=EXCLUDED.requested_ts, "
                    "status='pending', decided_ts=NULL" + keep, (site, user, requested_by, ts))
            row = self._q('SELECT status FROM consent_requests WHERE site=%s AND "user"=%s',
                          (site, user)).fetchone()
        return row["status"] if row else "pending"

    def list_consent_requests(self, status="pending", limit=100):
        return [dict(r) for r in self._q(
            'SELECT site,"user",requested_by,requested_ts,status,decided_ts FROM consent_requests '
            "WHERE status=%s ORDER BY requested_ts DESC LIMIT %s", (status, int(limit))).fetchall()]

    def decide_consent_request(self, site, user, status, ts) -> bool:
        with self._session():
            cur = self._q('UPDATE consent_requests SET status=%s, decided_ts=%s '
                          'WHERE site=%s AND "user"=%s AND status=\'pending\'',
                          (status, ts, site, user))
            return (cur.rowcount or 0) > 0

    # ---- user graph ----
    def load_user(self, site, user) -> UserGraph:
        with self._session():
            ug = self._load_user_unlocked(site, user)
        ug._persisted_edges = set(ug.edges)
        ug._persisted_history = {a: tuple(ts) for a, ts in ug.history.items()}
        return ug

    def _load_user_unlocked(self, site, user) -> UserGraph:
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
        persisted_edges = getattr(ug, "_persisted_edges", None)
        persisted_hist = getattr(ug, "_persisted_history", None)
        with self._session(), self._conn.transaction(), self._conn.cursor() as c:
            if persisted_edges is None or persisted_hist is None:
                c.execute('DELETE FROM user_edges WHERE site=%s AND "user"=%s', (ug.site, ug.user))
                c.execute('DELETE FROM user_history WHERE site=%s AND "user"=%s', (ug.site, ug.user))
                hist_rows = [(ug.site, ug.user, a, t) for a, ts in ug.history.items() for t in ts]
            else:
                removed = persisted_edges - set(ug.edges)
                if removed:
                    c.executemany('DELETE FROM user_edges WHERE site=%s AND "user"=%s AND attr=%s',
                                  [(ug.site, ug.user, a) for a in removed])
                hist_rows = []
                for a in set(persisted_hist) - set(ug.history):
                    c.execute('DELETE FROM user_history WHERE site=%s AND "user"=%s AND attr=%s',
                              (ug.site, ug.user, a))
                for a, ts in ug.history.items():
                    before = persisted_hist.get(a, ())
                    n0 = len(before)
                    if len(ts) >= n0 and tuple(ts[:n0]) == before:
                        tail = ts[n0:]
                    else:
                        c.execute('DELETE FROM user_history WHERE site=%s AND "user"=%s AND attr=%s',
                                  (ug.site, ug.user, a))
                        tail = ts
                    hist_rows.extend((ug.site, ug.user, a, t) for t in tail)
            if ug.edges:
                c.executemany(
                    'INSERT INTO user_edges VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) '
                    'ON CONFLICT(site,"user",attr) DO UPDATE SET weight=EXCLUDED.weight, '
                    'confidence=EXCLUDED.confidence, source=EXCLUDED.source, '
                    'last_reinforced=EXCLUDED.last_reinforced, hits=EXCLUDED.hits, '
                    'fast=EXCLUDED.fast, salience=EXCLUDED.salience, provenance=EXCLUDED.provenance',
                    [(ug.site, ug.user, a, e.weight, e.confidence, e.source,
                      e.last_reinforced, e.hits, e.fast, e.salience, e.provenance)
                     for a, e in ug.edges.items()])
            c.execute('DELETE FROM user_numeric WHERE site=%s AND "user"=%s', (ug.site, ug.user))
            if ug.numeric:
                c.executemany('INSERT INTO user_numeric VALUES(%s,%s,%s,%s)',
                              [(ug.site, ug.user, k, str(v)) for k, v in ug.numeric.items()])
            if hist_rows:
                c.executemany('INSERT INTO user_history VALUES(%s,%s,%s,%s)', hist_rows)
        ug._persisted_edges = set(ug.edges)
        ug._persisted_history = {a: tuple(ts) for a, ts in ug.history.items()}

    def delete_user(self, site, user):
        with self._session(), self._conn.transaction():
            persons = [r["person"] for r in self._q(
                "SELECT DISTINCT person FROM identities WHERE site=%s AND local_user=%s",
                (site, user)).fetchall()]
            self._q("DELETE FROM identities WHERE site=%s AND local_user=%s", (site, user))
            for person in persons:
                left = self._q("SELECT 1 FROM identities WHERE person=%s LIMIT 1",
                               (person,)).fetchone()
                if left is None:
                    self._q("DELETE FROM share_policy WHERE person=%s", (person,))
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
            for t in ("user_edges", "user_numeric", "user_history", "events", "consents",
                      "consent_requests", "settings"):
                self._q(f'DELETE FROM {t} WHERE site=%s AND "user"=%s', (site, user))
            self._q('DELETE FROM canonicalization_suggestions WHERE site=%s AND "user"=%s',
                    (site, user))
            self._q('DELETE FROM document_tags WHERE site=%s AND "user"=%s',
                    (site, user))
            self._q('DELETE FROM documents WHERE site=%s AND "user"=%s',
                    (site, user))
            self._q('DELETE FROM assets WHERE site=%s AND "user"=%s', (site, user))

    def export_user(self, site, user) -> Dict:
        ug = self.load_user(site, user)
        return {"site": site, "user": user,
                "edges": {a: e.__dict__ for a, e in ug.edges.items()},
                "numeric": ug.numeric, "events": self.recall(site, user, limit=100000),
                "settings": self.list_settings(site, user),
                "consent": self.has_consent(site, user)}

    # ---- pinned settings ----
    def upsert_setting(self, site, user, key, value, text, ts):
        self._q('INSERT INTO settings(site,"user",key,value,text,ts) VALUES(%s,%s,%s,%s,%s,%s) '
                'ON CONFLICT(site,"user",key) DO UPDATE SET value=EXCLUDED.value, '
                'text=EXCLUDED.text, ts=EXCLUDED.ts', (site, user, key, value, text, ts))

    def list_settings(self, site, user) -> List[Dict]:
        return [dict(r) for r in self._q(
            'SELECT key,value,text,ts FROM settings WHERE site=%s AND "user"=%s ORDER BY key',
            (site, user)).fetchall()]

    def delete_setting(self, site, user, key) -> bool:
        return (self._q('DELETE FROM settings WHERE site=%s AND "user"=%s AND key=%s',
                        (site, user, key)).rowcount or 0) > 0

    # ---- per-site policy ----
    def get_site_policy(self, site) -> Dict[str, str]:
        return {r["key"]: r["value"] for r in self._q(
            "SELECT key,value FROM site_policy WHERE site=%s", (site,)).fetchall()}

    def set_site_policy(self, site, key, value):
        self._q("INSERT INTO site_policy(site,key,value) VALUES(%s,%s,%s) "
                "ON CONFLICT(site,key) DO UPDATE SET value=EXCLUDED.value",
                (site, key, str(value)))

    # ---- verifiable audit log ----
    def append_audit(self, site, user, ts, action, detail, key):
        """Same HMAC chain as SQLiteStore. The (site, user) advisory lock keeps
        sequence numbers gap-free when several processes append at once."""
        with self._session() as conn, conn.transaction():
            conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                         (self._lock_name("audit", site, str(user)),))
            r = conn.execute(
                'SELECT seq, hash FROM audit WHERE site=%s AND "user"=%s '
                'ORDER BY seq DESC LIMIT 1', (site, user)).fetchone()
            seq = (r["seq"] + 1) if r else 0
            prev = r["hash"] if r else GENESIS
            h = entry_hash(key, prev, seq, ts, action, detail)
            conn.execute('INSERT INTO audit(site,"user",seq,ts,action,detail,prev_hash,hash) '
                         'VALUES(%s,%s,%s,%s,%s,%s,%s,%s)',
                         (site, user, seq, ts, action, json.dumps(detail), prev, h))
            return {"seq": seq, "hash": h}

    def read_audit(self, site, user):
        return [{"seq": r["seq"], "ts": r["ts"], "action": r["action"],
                 "detail": json.loads(r["detail"]), "hash": r["hash"]}
                for r in self._q('SELECT * FROM audit WHERE site=%s AND "user"=%s ORDER BY seq',
                                 (site, user)).fetchall()]

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

    def load_assoc_neighborhood(self, site, nodes, hops=2, user=None, min_users=1) -> AssocGraph:
        """Edges reachable from ``nodes`` within ``hops`` (see SQLiteStore)."""
        ag = AssocGraph(site)
        min_users = int(min_users or 1)
        frontier = set(n for n in nodes if n)
        seen = set()
        with self._session():
            for _ in range(max(1, int(hops))):
                batch = sorted(frontier - seen)
                if not batch:
                    break
                seen |= set(batch)
                found = set()
                if min_users <= 1:
                    rows = self._q("SELECT e.a,e.b,e.weight FROM assoc_edges e WHERE e.site=%s "
                                   "AND (e.a = ANY(%s) OR e.b = ANY(%s))",
                                   (site, batch, batch)).fetchall()
                elif user is None:
                    rows = self._q("SELECT e.a,e.b,e.weight FROM assoc_edges e WHERE e.site=%s "
                                   "AND e.users>=%s AND (e.a = ANY(%s) OR e.b = ANY(%s))",
                                   (site, min_users, batch, batch)).fetchall()
                else:
                    rows = self._q(
                        "SELECT e.a,e.b,e.weight FROM assoc_edges e "
                        "LEFT JOIN assoc_edge_users u ON u.site=e.site AND u.a=e.a "
                        'AND u.b=e.b AND u."user"=%s '
                        'WHERE e.site=%s AND (e.users>=%s OR u."user" IS NOT NULL) '
                        "AND (e.a = ANY(%s) OR e.b = ANY(%s))",
                        (user, site, min_users, batch, batch)).fetchall()
                for r in rows:
                    ag.edges[(r["a"], r["b"])] = r["weight"]
                    found.add(r["a"]); found.add(r["b"])
                frontier = found
        return ag

    def load_assoc_pairs(self, site, pairs) -> AssocGraph:
        ag = AssocGraph(site)
        keys = list(dict.fromkeys(self._assoc_key(a, b) for a, b in pairs))
        with self._session():
            for a, b in keys:
                r = self._q("SELECT weight FROM assoc_edges WHERE site=%s AND a=%s AND b=%s",
                            (site, a, b)).fetchone()
                if r is not None:
                    ag.edges[(a, b)] = r["weight"]
        return ag

    def save_assoc(self, ag: AssocGraph, contributor_user=None, touched_pairs=None):
        touched_pairs = [self._assoc_key(a, b) for a, b in (touched_pairs or [])]
        keys = touched_pairs if touched_pairs else list(ag.edges)
        rows = [(ag.site, k[0], k[1], ag.edges[k]) for k in dict.fromkeys(keys) if k in ag.edges]
        with self._session(), self._conn.transaction(), self._conn.cursor() as c:
            if rows:
                c.executemany("INSERT INTO assoc_edges(site,a,b,weight) VALUES(%s,%s,%s,%s) "
                              "ON CONFLICT(site,a,b) DO UPDATE SET weight=EXCLUDED.weight", rows)
            if contributor_user and touched_pairs:
                c.executemany(
                    'INSERT INTO assoc_edge_users(site,"user",a,b,hits) '
                    'VALUES(%s,%s,%s,%s,1) '
                    'ON CONFLICT(site,"user",a,b) DO UPDATE SET hits=assoc_edge_users.hits+1',
                    [(ag.site, contributor_user, a, b) for a, b in touched_pairs])
                self._refresh_assoc_user_counts(ag.site, touched_pairs)

    # ---- cabinet ----
    def append_event(self, ev: Event):
        with self._session():
            row = self._q(
                'INSERT INTO events(site,"user",ts,type,payload,attrs) '
                'VALUES(%s,%s,%s,%s,%s,%s) RETURNING id',
                (ev.site, ev.user, ev.ts, ev.type, json.dumps(ev.payload),
                 json.dumps(ev.attrs))).fetchone()
            return int(row["id"])

    def recall(self, site, user, type=None, contains=None, limit=20) -> List[Dict]:
        q = 'SELECT ts,type,payload,attrs FROM events WHERE site=%s AND "user"=%s'
        args = [site, user]
        if type: q += " AND type=%s"; args.append(type)
        if contains: q += " AND payload LIKE %s"; args.append(f"%{contains}%")
        q += " ORDER BY ts DESC, id DESC LIMIT %s"; args.append(limit)
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

    def events_site_chronological(self, site) -> List[Dict]:
        rows = self._q(
            'SELECT id,"user",attrs FROM events WHERE site=%s ORDER BY id ASC',
            (site,),
        ).fetchall()
        return [
            {"id": row["id"], "user": row["user"],
             "attrs": json.loads(row["attrs"])}
            for row in rows
        ]

    def replace_assoc_site(self, ag: AssocGraph, contributor_hits: Dict):
        rows = [
            (ag.site, user, a, b, int(hits))
            for (user, a, b), hits in contributor_hits.items()
            if int(hits) > 0
        ]
        users_by_pair = {}
        for _site, user, a, b, _hits in rows:
            users_by_pair.setdefault((a, b), set()).add(user)
        with self._session(), self._conn.transaction(), self._conn.cursor() as cursor:
            cursor.execute(
                "DELETE FROM assoc_edge_users WHERE site=%s", (ag.site,))
            cursor.execute("DELETE FROM assoc_edges WHERE site=%s", (ag.site,))
            cursor.executemany(
                "INSERT INTO assoc_edges(site,a,b,weight,users) "
                "VALUES(%s,%s,%s,%s,%s)",
                [(ag.site, a, b, weight, len(users_by_pair.get((a, b), set())))
                 for (a, b), weight in ag.edges.items()],
            )
            cursor.executemany(
                'INSERT INTO assoc_edge_users(site,"user",a,b,hits) '
                'VALUES(%s,%s,%s,%s,%s)',
                rows,
            )

    def delete_document_artifacts(self, site, user, source_sha256,
                                  document_id=None) -> Dict:
        with self._session():
            event_rows = self._q(
                'SELECT id,ts,type,payload,attrs FROM events '
                'WHERE site=%s AND "user"=%s ORDER BY id ASC',
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

            suggestion_rows = self._q(
                'SELECT suggestion_id,payload FROM canonicalization_suggestions '
                'WHERE site=%s AND "user"=%s',
                (site, user),
            ).fetchall()
            suggestion_ids = [
                row["suggestion_id"]
                for row in suggestion_rows
                if (json.loads(row["payload"]).get("source_sha256") == source_sha256 or
                    (document_id and json.loads(row["payload"]).get("document_id") == document_id))
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

    # ---- durable document catalog and approved tag provenance ----
    @staticmethod
    def _document_row(row):
        if row is None:
            return None
        out = dict(row)
        out["pinned"] = bool(out["pinned"])
        out["authoritative"] = bool(out["authoritative"])
        return out

    def insert_document(self, row):
        with self._session():
            self._q(
                'INSERT INTO documents(document_id,site,"user",source_sha256,'
                'source_name,markdown_path,envelope_path,mime_type,extraction_quality,'
                'warning_count,block_count,created_ts,imported_ts,status,pinned,'
                'authoritative,superseded_by) '
                'VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',
                (row["document_id"], row["site"], row["user"], row["source_sha256"],
                 row["source_name"], row["markdown_path"], row["envelope_path"],
                 row["mime_type"], row["extraction_quality"], int(row["warning_count"]),
                 int(row["block_count"]), float(row["created_ts"]),
                 float(row["imported_ts"]), row["status"], int(row.get("pinned", False)),
                 int(row.get("authoritative", False)), row.get("superseded_by", "")),
            )
        return self.get_document(row["site"], row["user"], row["document_id"])

    def get_document(self, site, user, document_id_or_sha256):
        row = self._q(
            'SELECT * FROM documents WHERE site=%s AND "user"=%s '
            'AND (document_id=%s OR source_sha256=%s) LIMIT 1',
            (site, user, document_id_or_sha256, document_id_or_sha256),
        ).fetchone()
        return self._document_row(row)

    def list_documents(self, site, user, statuses=None, limit=100, offset=0):
        statuses = list(statuses or ["active"])
        if not statuses:
            return []
        rows = self._q(
            'SELECT * FROM documents WHERE site=%s AND "user"=%s '
            'AND status = ANY(%s) ORDER BY pinned DESC,imported_ts DESC,document_id ASC '
            'LIMIT %s OFFSET %s',
            (site, user, statuses, int(limit), int(offset)),
        ).fetchall()
        return [self._document_row(row) for row in rows]

    def count_documents(self, site, user, statuses=None):
        statuses = list(statuses or ["active"])
        if not statuses:
            return 0
        row = self._q(
            'SELECT COUNT(*) AS n FROM documents WHERE site=%s AND "user"=%s '
            'AND status = ANY(%s)',
            (site, user, statuses),
        ).fetchone()
        return int(row["n"])

    def update_document(self, site, user, document_id, **changes):
        allowed = {"status", "pinned", "authoritative", "superseded_by"}
        items = [(key, value) for key, value in changes.items() if key in allowed]
        if not items:
            return self.get_document(site, user, document_id)
        sets = ",".join(key + "=%s" for key, _value in items)
        values = [int(value) if key in ("pinned", "authoritative") else value
                  for key, value in items]
        with self._session():
            self._q(
                'UPDATE documents SET ' + sets +
                ' WHERE site=%s AND "user"=%s AND document_id=%s',
                (*values, site, user, document_id),
            )
        return self.get_document(site, user, document_id)

    def add_document_tags(self, site, user, document_id, tags,
                          suggestion_id, approved_ts):
        rows = [(document_id, site, user, tag, "human_approved",
                 suggestion_id or "", float(approved_ts)) for tag in tags]
        with self._session(), self._conn.cursor() as cursor:
            cursor.executemany(
                'INSERT INTO document_tags(document_id,site,"user",tag,provenance,'
                'suggestion_id,approved_ts) VALUES(%s,%s,%s,%s,%s,%s,%s) '
                'ON CONFLICT(document_id,tag) DO UPDATE SET '
                'provenance=EXCLUDED.provenance,suggestion_id=EXCLUDED.suggestion_id,'
                'approved_ts=EXCLUDED.approved_ts',
                rows,
            )
        return self.list_document_tags(site, user, document_id)

    def list_document_tags(self, site, user, document_id=None):
        query = 'SELECT * FROM document_tags WHERE site=%s AND "user"=%s'
        args = [site, user]
        if document_id:
            query += " AND document_id=%s"
            args.append(document_id)
        query += " ORDER BY tag,document_id"
        return [dict(row) for row in self._q(query, tuple(args)).fetchall()]

    def delete_document_catalog(self, site, user, document_id):
        with self._session():
            tags = self._q(
                'SELECT tag FROM document_tags WHERE site=%s AND "user"=%s '
                'AND document_id=%s', (site, user, document_id)).fetchall()
            self._q(
                'DELETE FROM document_tags WHERE site=%s AND "user"=%s '
                'AND document_id=%s', (site, user, document_id))
            result = self._q(
                'DELETE FROM documents WHERE site=%s AND "user"=%s '
                'AND document_id=%s', (site, user, document_id))
        return {"documents_deleted": int(result.rowcount),
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

    def insert_asset(self, row):
        with self._session():
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
        with self._session():
            self._q(
                'UPDATE assets SET sensitive=%s WHERE site=%s AND "user"=%s '
                "AND id=%s AND status='active'",
                (int(sensitive), site, user, asset_id),
            )
        return self.get_asset(site, user, asset_id)

    def delete_asset_row(self, site, user, asset_id):
        with self._session():
            self._q(
                'DELETE FROM assets WHERE site=%s AND "user"=%s AND id=%s',
                (site, user, asset_id),
            )

    def delete_asset_artifacts(self, site, user, asset_id, source_sha256):
        with self._session():
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
        """Replace the site's prior with ``pp`` (stale attributes removed)."""
        with self._session(), self._conn.transaction(), self._conn.cursor() as c:
            c.execute("DELETE FROM prior_node WHERE site=%s", (pp.site,))
            if pp._sum:
                c.executemany("INSERT INTO prior_node VALUES(%s,%s,%s,%s) "
                              "ON CONFLICT(site,attr) DO UPDATE SET sum=EXCLUDED.sum, n=EXCLUDED.n",
                              [(pp.site, a, pp._sum[a], pp._n[a]) for a in pp._sum])
            c.execute("INSERT INTO prior_meta VALUES(%s,%s) "
                      "ON CONFLICT(site) DO UPDATE SET n_users=EXCLUDED.n_users",
                      (pp.site, pp.n_users))

    # ---- identities + sharing ----
    def link_identity(self, person, site, local_user, ts=0.0):
        with self._session():
            self._q("INSERT INTO identities(person,site,local_user,ts) VALUES(%s,%s,%s,%s) "
                    "ON CONFLICT DO NOTHING", (person, site, local_user, ts))

    def unlink_identity(self, person, site, local_user):
        with self._session():
            self._q("DELETE FROM identities WHERE person=%s AND site=%s AND local_user=%s",
                    (person, site, local_user))

    def list_identities(self, person):
        return [(r["site"], r["local_user"]) for r in
                self._q("SELECT site,local_user FROM identities WHERE person=%s", (person,)).fetchall()]

    def set_share(self, person, target_site, category, allowed):
        with self._session():
            self._q("INSERT INTO share_policy(person,target_site,category,allowed) VALUES(%s,%s,%s,%s) "
                    "ON CONFLICT(person,target_site,category) DO UPDATE SET allowed=EXCLUDED.allowed",
                    (person, target_site, category, int(allowed)))

    def get_shares(self, person, target_site):
        return {r["category"]: bool(r["allowed"]) for r in
                self._q("SELECT category,allowed FROM share_policy WHERE person=%s AND target_site=%s",
                        (person, target_site)).fetchall()}

    # ---- typed entity layer ----
    def create_entity(self, entity_id, site, user, kind, display_name, created_at):
        with self._session():
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
        with self._session():
            self._q('INSERT INTO entity_aliases(site,"user",alias_attr,entity_id,source,confidence) '
                    'VALUES(%s,%s,%s,%s,%s,%s) '
                    'ON CONFLICT(site,"user",alias_attr) DO UPDATE SET '
                    'entity_id=EXCLUDED.entity_id, source=EXCLUDED.source, confidence=EXCLUDED.confidence',
                    (site, user, alias_attr, entity_id, source, float(confidence)))

    def unlink_entity_alias(self, site, user, entity_id, alias_attr):
        with self._session():
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
        with self._session():
            self._q(
                'UPDATE entities SET kind=%s WHERE site=%s AND "user"=%s AND entity_id=%s',
                (kind, site, user, entity_id))

    def set_entity_field(self, entity_id, field, value, provenance, ts):
        with self._session():
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
        with self._session():
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
        with self._session():
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
        with self._session():
            cur = self._q("DELETE FROM relation_facts WHERE fact_id=%s", (fact_id,))
            return cur.rowcount > 0

    def delete_entity_relation(self, site, user, subject_id, relation, object_id):
        with self._session():
            self._q('DELETE FROM relation_facts WHERE site=%s AND "user"=%s '
                    'AND subject_id=%s AND relation=%s AND object_id=%s',
                    (site, user, subject_id, relation, object_id))
            self._q('DELETE FROM entity_relations WHERE site=%s AND "user"=%s '
                    'AND subject_id=%s AND relation=%s AND object_id=%s',
                    (site, user, subject_id, relation, object_id))

    def delete_entity(self, site, user, entity_id):
        with self._session():
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
        with self._session():
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
        with self._session():
            self._q(
                "UPDATE canonicalization_suggestions SET status=%s, decided_ts=%s "
                "WHERE suggestion_id=%s",
                (status, float(decided_ts), suggestion_id))
        return self.get_suggestion(suggestion_id)

    def purge_expired_suggestions(self, site, user, now, ttl_days):
        cutoff = float(now) - float(ttl_days)
        with self._session():
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
        with self._session():
            with self._conn.cursor() as c:
                c.executemany(
                    "DELETE FROM canonicalization_suggestions WHERE suggestion_id=%s",
                    [(row["suggestion_id"],) for row in drop])
        return len(drop)

    def delete_suggestions_for_entity(self, site, user, entity_id):
        with self._session():
            cur = self._q(
                'DELETE FROM canonicalization_suggestions WHERE site=%s AND "user"=%s '
                'AND (payload LIKE %s OR payload LIKE %s OR payload LIKE %s)',
                (site, user, f'%"entity_id":"{entity_id}"%',
                 f'%"subject_id":"{entity_id}"%', f'%"object_id":"{entity_id}"%'))
            return cur.rowcount

    def list_users(self, site):
        return [r["user"] for r in self._q(
            'SELECT DISTINCT "user" FROM user_edges WHERE site=%s', (site,)).fetchall()]
