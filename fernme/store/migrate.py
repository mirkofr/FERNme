"""``fernme-migrate``: create or upgrade FERNme's Postgres tables.

For host applications that run their own migrations and start FERNme with
``PostgresStore(..., auto_migrate=False)``::

    fernme-migrate --dsn postgresql://... --schema fernme
    fernme-migrate --check            # exit 1 if the schema is missing or old

The DSN can also come from ``FERNME_PG_DSN`` (or ``DATABASE_URL``) and the
schema from ``FERNME_PG_SCHEMA``. Migrations are idempotent and serialize on an
advisory lock, so running them from several deploy jobs at once is safe.
"""
from __future__ import annotations

import argparse
import os
import sys


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="fernme-migrate", description=__doc__.split("\n")[0])
    parser.add_argument("--dsn", default=os.environ.get("FERNME_PG_DSN")
                        or os.environ.get("DATABASE_URL"),
                        help="Postgres connection string (default: FERNME_PG_DSN or DATABASE_URL)")
    parser.add_argument("--schema", default=os.environ.get("FERNME_PG_SCHEMA") or None,
                        help="schema for FERNme's tables (default: FERNME_PG_SCHEMA, else search_path)")
    parser.add_argument("--check", action="store_true",
                        help="only check the schema version; exit 1 if a migration is needed")
    ns = parser.parse_args(argv)
    if not ns.dsn:
        parser.error("no DSN: pass --dsn or set FERNME_PG_DSN")
    from .postgres_store import SCHEMA_VERSION, PostgresStore, SchemaVersionError
    if ns.check:
        try:
            store = PostgresStore(ns.dsn, schema=ns.schema, auto_migrate=False)
        except SchemaVersionError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        store.close()
        print(f"FERNme schema is current (version {SCHEMA_VERSION}).")
        return 0
    version = PostgresStore.migrate_database(ns.dsn, schema=ns.schema)
    where = f" in schema '{ns.schema}'" if ns.schema else ""
    print(f"FERNme schema version {version}{where}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
