"""v0.4.1 on a REAL Postgres 16 (rootless pgserver): audit chain, schema name,
pools, migrations as a separate step, concurrent writers in several processes,
pinned settings and site policy. Skips without pgserver. Fictional data only."""
import multiprocessing as mp
import shutil
import tempfile
import threading

import pytest

pgserver = pytest.importorskip("pgserver")
psycopg = pytest.importorskip("psycopg")

from fernme.service import FernService
from fernme.store import migrate as migrate_cli
from fernme.store.postgres_store import PostgresStore, SchemaVersionError

SITE = "embed.example"


@pytest.fixture(scope="module")
def pg():
    d = tempfile.mkdtemp(prefix="pgdata_")
    srv = pgserver.get_server(d)
    yield srv.get_uri()
    srv.cleanup()
    shutil.rmtree(d, ignore_errors=True)


def _tables(dsn, schema):
    with psycopg.connect(dsn) as conn:
        return {r[0] for r in conn.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema=%s",
            (schema,))}


# ---- 1. audit on Postgres -------------------------------------------------------

def test_audit_chain_on_postgres_matches_sqlite_behaviour(pg):
    svc = FernService(store=PostgresStore(pg, schema="audit_t"))
    svc.consent(SITE, "dana", True)
    svc.observe(SITE, "dana", "chat", {"tags": ["pref:tea"]}, ts=1.0)
    svc.edit(SITE, "dana", "pref:tea", 5.0)
    log = svc.audit_log(SITE, "dana")
    assert [e["seq"] for e in log] == [0, 1, 2]
    assert [e["action"] for e in log] == ["consent", "observe", "edit"]
    assert svc.verify_audit(SITE, "dana")["ok"] is True
    with psycopg.connect(pg) as conn:
        conn.execute("UPDATE audit_t.audit SET detail='{\"n_attrs\": 9, \"type\": \"chat\"}' "
                     "WHERE site=%s AND \"user\"='dana' AND seq=1", (SITE,))
    out = svc.verify_audit(SITE, "dana")
    assert out["ok"] is False and out["broken_at_seq"] == 1


# ---- 5. schema, migrations, pools ---------------------------------------------------

def test_schema_keeps_tables_out_of_public(pg):
    before = _tables(pg, "public")
    PostgresStore(pg, schema="iso_a").close()
    assert {"settings", "audit", "user_edges", "fernme_schema_version"} <= _tables(pg, "iso_a")
    assert _tables(pg, "public") == before
    a = FernService(store=PostgresStore(pg, schema="iso_a"))
    b = FernService(store=PostgresStore(pg, schema="iso_b"))
    a.consent(SITE, "dana", True)
    a.set_setting(SITE, "dana", "plot.style", "box")
    assert b.store.has_consent(SITE, "dana") is False


def test_auto_migrate_off_needs_the_migrate_command(pg, capsys):
    with pytest.raises(SchemaVersionError, match="fernme-migrate"):
        PostgresStore(pg, schema="mig_t", auto_migrate=False)
    assert migrate_cli.main(["--dsn", pg, "--schema", "mig_t2", "--check"]) == 1
    assert migrate_cli.main(["--dsn", pg, "--schema", "mig_t2"]) == 0
    assert migrate_cli.main(["--dsn", pg, "--schema", "mig_t2", "--check"]) == 0
    store = PostgresStore(pg, schema="mig_t2", auto_migrate=False)
    svc = FernService(store=store)
    svc.consent(SITE, "dana", True)
    assert svc.verify_audit(SITE, "dana")["ok"] is True
    assert migrate_cli.main(["--dsn", pg, "--schema", "mig_t2"]) == 0   # idempotent


def test_dedicated_pool_is_thread_safe(pg):
    store = PostgresStore(pg, schema="pool_t", pool_size=(2, 6))
    svc = FernService(store=store)
    users = [f"u{i}" for i in range(6)]
    for u in users:
        svc.consent(SITE, u, True)
    errors = []

    def work(user):
        try:
            for t in range(10):
                svc.observe(SITE, user, "chat", {"tags": ["pref:shared", f"pref:{user}"]},
                            ts=float(t))
                svc.observe(SITE, "u0", "chat", {"tags": ["pref:hot"]}, ts=float(t))
        except Exception as exc:                  # pragma: no cover - reported below
            errors.append(exc)
    threads = [threading.Thread(target=work, args=(u,)) for u in users]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    assert svc.store.load_user(SITE, "u0").edges["pref:hot"].hits == 60
    assert all(svc.store.load_user(SITE, u).edges["pref:shared"].hits == 10 for u in users)
    store.close()


def test_host_pool_connections_are_given_back_unchanged(pg):
    from psycopg_pool import ConnectionPool
    pool = ConnectionPool(pg, min_size=1, max_size=2, open=True)     # host defaults
    store = PostgresStore(pg, schema="host_t")                       # migrate once
    store.close()
    svc = FernService(store=PostgresStore(schema="host_t", pool=pool))
    svc.consent(SITE, "dana", True)
    svc.set_setting(SITE, "dana", "plot.style", "box")
    assert svc.card(SITE, "dana")["settings"] == {"plot.style": "box"}
    with pool.connection() as conn:
        assert conn.autocommit is False
        assert conn.execute("SHOW search_path").fetchone()[0] == '"$user", public'
        assert conn.execute("SELECT to_regclass('settings')").fetchone()[0] is None
    pool.close()


# ---- 4. several processes writing at once ------------------------------------

def _writer(dsn, schema, worker, n, barrier):
    svc = FernService(store=PostgresStore(dsn, schema=schema, auto_migrate=False))
    barrier.wait()
    for t in range(n):
        svc.observe(SITE, "shared", "chat", {"tags": ["pref:shared"]}, ts=float(t))
        svc.observe(SITE, f"own{worker}", "chat", {"tags": ["pref:mine"]}, ts=float(t))
        svc.set_setting(SITE, "shared", "last.writer", f"w{worker}")
    svc.store.close()


def test_concurrent_processes_do_not_lose_updates(pg):
    schema, workers, n = "proc_t", 4, 15
    setup = FernService(store=PostgresStore(pg, schema=schema))
    for u in ["shared"] + [f"own{w}" for w in range(workers)]:
        setup.consent(SITE, u, True)
    ctx = mp.get_context("spawn")
    barrier = ctx.Barrier(workers)
    procs = [ctx.Process(target=_writer, args=(pg, schema, w, n, barrier))
             for w in range(workers)]
    for p in procs:
        p.start()
    for p in procs:
        p.join(120)
    assert all(p.exitcode == 0 for p in procs)
    edges = setup.store.load_user(SITE, "shared").edges
    assert edges["pref:shared"].hits == workers * n
    for w in range(workers):
        assert setup.store.load_user(SITE, f"own{w}").edges["pref:mine"].hits == n
    log = setup.audit_log(SITE, "shared")
    assert [e["seq"] for e in log] == list(range(len(log)))
    assert len(log) == 1 + 2 * workers * n               # consent + observe + setting each
    assert setup.verify_audit(SITE, "shared")["ok"] is True
    assert setup.get_settings(SITE, "shared")["settings"]["last.writer"] in {
        f"w{w}" for w in range(workers)}


# ---- 3 / 7. settings and site policy on Postgres ------------------------------

def test_settings_and_site_policy_on_postgres(pg):
    svc = FernService(store=PostgresStore(pg, schema="set_t"))
    svc.consent(SITE, "dana", True)
    svc.set_setting(SITE, "dana", "plot.style", "box")
    svc.set_setting(SITE, "dana", "plot.style", "violin")
    assert svc.card(SITE, "dana")["settings"] == {"plot.style": "violin"}
    assert svc.export(SITE, "dana")["settings"][0]["value"] == "violin"
    assert svc.set_site_policy(SITE, cold_start=False)["cold_start"] is False
    assert svc.site_policy(SITE) == {"site": SITE, "prior": True, "cold_start": False}
    svc.delete(SITE, "dana")
    assert svc.store.list_settings(SITE, "dana") == []


# ---- regressions from the 0.4.1 review ------------------------------------------

def test_restart_does_no_ddl_while_writers_hold_locks(pg):
    PostgresStore(pg, schema="ddl_t").close()
    with psycopg.connect(pg) as writer:               # a live write transaction
        writer.execute("LOCK TABLE ddl_t.user_history IN ROW EXCLUSIVE MODE")
        writer.execute("LOCK TABLE ddl_t.user_edges IN ROW EXCLUSIVE MODE")
        done = {}

        def start():
            try:
                PostgresStore(pg, schema="ddl_t").close()     # default auto_migrate=True
                done["ok"] = True
            except Exception as exc:                  # pragma: no cover
                done["err"] = exc
        t = threading.Thread(target=start)
        t.start()
        t.join(10)
        assert done.get("ok") is True, done            # used to wait on CREATE INDEX / ALTER
        writer.rollback()


def test_schema_never_falls_back_to_public(pg):
    PostgresStore(pg).close()                         # a 0.4.1 install in public
    assert migrate_cli.main(["--dsn", pg, "--schema", "tenant_x", "--check"]) == 1
    with pytest.raises(SchemaVersionError):
        PostgresStore(pg, schema="tenant_x", auto_migrate=False)
    store = PostgresStore(pg, schema="tenant_x")
    svc = FernService(store=store)
    svc.consent(SITE, "only-in-tenant-x", True)
    with psycopg.connect(pg) as conn:
        assert conn.execute("SELECT count(*) FROM public.consents WHERE \"user\"=%s",
                            ("only-in-tenant-x",)).fetchone()[0] == 0


def _first_start(dsn, schema, pooled, barrier, out):
    barrier.wait()
    try:
        kwargs = {"pool_size": (1, 2)} if pooled else {}
        PostgresStore(dsn, schema=schema, **kwargs).close()
        out.put("ok")
    except Exception as exc:                          # pragma: no cover
        out.put(repr(exc))


@pytest.mark.parametrize("pooled", [False, True])
def test_concurrent_first_start_with_a_schema(pg, pooled):
    schema = f"race_{'p' if pooled else 's'}"
    ctx = mp.get_context("spawn")
    barrier, out = ctx.Barrier(6), ctx.Queue()
    procs = [ctx.Process(target=_first_start, args=(pg, schema, pooled, barrier, out))
             for _ in range(6)]
    for p in procs:
        p.start()
    for p in procs:
        p.join(120)
    results = [out.get(timeout=5) for _ in procs]
    assert results == ["ok"] * 6, results


def test_postgres_secret_is_never_the_legacy_key(pg):
    a = FernService(store=PostgresStore(pg, schema="sec_t"), secret_key="fictional-a")
    a.consent(SITE, "dana", True)                     # audit rows signed with an explicit key
    b = FernService(store=PostgresStore(pg, schema="sec_t"))
    assert b.audit_key_legacy is False and b.secret_source == "database"
    FernService(store=PostgresStore(pg, schema="sec_t"), strict=True)    # not refused
