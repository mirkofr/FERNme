# Embedding FERNme in a server application

FERNme is a library first. A web app or agent platform can run it inside its own
backend: keep the memory in the app's Postgres, take the user from the app's own
sign-in, and give agents the app's own tools. This page covers that setup.

## Store

```python
from fernme.service import FernService
from fernme.store.postgres_store import PostgresStore

store = PostgresStore(
    "postgresql://app@db/app",
    schema="fernme",          # all FERNme tables in their own schema
    pool_size=(1, 10),        # dedicated psycopg-pool (pip install "fernme[postgres]")
    auto_migrate=False,       # no DDL at startup; run fernme-migrate in your deploy
)
svc = FernService(store=store, secret_key=SECRET_FROM_YOUR_VAULT, strict=True)
```

| `PostgresStore` argument | default | meaning |
|---|---|---|
| `dsn` | required unless `pool` | libpq connection string |
| `schema` | `None` (connection's `search_path`) | schema for FERNme's tables; created by migrations |
| `pool_size` | `None` | `(min, max)` or an int: FERNme creates and owns a `psycopg_pool.ConnectionPool` |
| `pool` | `None` | borrow connections from your own `psycopg_pool.ConnectionPool`. FERNme sets autocommit, dict rows and `search_path` while it holds a connection and restores them when it gives it back (two extra round trips per operation when `schema` is set; `pool_size` avoids them) |
| `auto_migrate` | `True` | `False`: run no DDL, only check the schema version and raise `SchemaVersionError` naming the command to run |

Without `pool`/`pool_size`, one connection is shared under a lock: the
zero-config behaviour from earlier versions. `PostgresStore.create_pool(dsn,
schema, pool_size)` builds a correctly configured pool you can also share.
Call `store.close()` on shutdown.

## Migrations

```bash
fernme-migrate --dsn "$DATABASE_URL" --schema fernme      # create / upgrade
fernme-migrate --check --schema fernme                    # exit 1 if outdated
```

`--dsn` defaults to `FERNME_PG_DSN`, then `DATABASE_URL`; `--schema` to
`FERNME_PG_SCHEMA`. From Python: `PostgresStore.migrate_database(dsn, schema)`.
Migrations are idempotent and serialize on an advisory lock (schema creation
included), so parallel deploy jobs are safe. They run once per schema version:
on a current schema, startup with the default `auto_migrate=True` runs no DDL and
takes no table locks. An upgrade waits at most 30 s for table locks held by live
traffic (`PostgresStore.MIGRATION_LOCK_TIMEOUT`) and can be retried. The version
lives in `<schema>.fernme_schema_version`. With `schema=` the connection's
`search_path` is that schema only, so FERNme never touches tables in `public`.

## Service options

| `FernService` argument | env | meaning |
|---|---|---|
| `secret_key` | `FERNME_SECRET_KEY` (alias `FERNME_AUDIT_KEY`) | per-install secret for the audit chain and the prior's noise. Without it Postgres stores one secret in the database (`fernme_secret`) |
| `strict` | `FERNME_STRICT=1` | refuse the legacy public audit key and keys that would not survive a restart |
| `audit` | | `True` (default) audits; a store without an audit log then runs unaudited with a warning (an error in strict mode). `False` opts out silently |
| `cfg` | | `Config(...)`, e.g. `settings_max`, `prior_enabled`, `cold_start` |

## Users, sites and consent

Use one `site` per product surface (for example `"myapp"`) and your own stable
user id as `user`. Take both on the server from the authenticated session. Never
accept them from request bodies or tool arguments (see the hosted section in
`SECURITY.md`). Record consent once with `svc.consent(site, user, True)`; reads
and writes without consent raise `ConsentError`.

## Pinned settings

For explicit choices ("always use box plots"):

```python
svc.set_setting(site, user, "plot.style", "box", text="I like box plots")
svc.get_settings(site, user)    # {"settings": {"plot.style": "box"}, "details": [...]}
svc.clear_setting(site, user, "plot.style")
```

- One value per key; a new value replaces the old (`replaced` in the result).
- Never decay, and `card()` always returns all of them under `settings` (and in
  the wire string), whatever the context, card budget or prior.
- Keys: 1 to 64 characters of `a-z 0-9 . _ -`. Values: short plain data, up to
  `Config.settings_value_max` (120) characters and 8 words, letters in any script,
  digits, spaces and `. , : / + - _ # % ( ) ' & @`. Text is Unicode-normalized and
  invisible/bidi characters are removed; instruction phrases and links are
  rejected. The card shows values quoted (`plot.style="box"`). Still put the card
  in a data section of your prompt, not in system instructions.
- At most `Config.settings_max` (32) keys and `Config.settings_card_chars` (800)
  characters in total per user (about 200 tokens), so the card stays bounded.
  Keys whose first segment is in `Config.card_exclude_ns` are kept but not shown
  on the card.
- Consent-gated, in the audit chain (keyed reference, not the key name), and
  covered by `export`, `delete`, `forget_everywhere` and consent withdrawal.

Your agents' tools can wrap these directly, for example `get_preferences` →
`svc.card(site, user)["settings"]` (or the whole card) and `save_preference` →
`svc.set_setting(...)`. Softer, learned preferences still go through
`svc.observe(...)`.

## Population prior

New users can get a turn-one card seeded from other users (k-anonymous,
noisy, no sensitive attributes). To switch that off:

```python
svc.set_site_policy(site, cold_start=False)   # keep the prior, never seed guesses
svc.set_site_policy(site, prior=False)        # keep no prior at all for this site
```

Or globally with `Config(cold_start=False)` / `Config(prior_enabled=False)`.

## Concurrency

Every service write is one transaction. On Postgres it takes an advisory lock for
the (site, user) and, for writes that touch site-shared rows (the association
graph, the prior), one for the site. So several app servers can share a database
without losing updates. Settings writes take only the user lock. One site with
many users still serializes graph writes (`observe`) on the site lock. That is
fine at preference-memory rates, but measure it if you expect hundreds of writes
per second on a single site.
