"""CLI for backfilling catalog rows for pre-catalog (Phase 15) document
imports. Dry-run by default; pass --confirm to write. See
``FernService.backfill_documents`` for the full contract."""
from __future__ import annotations

import argparse
import json

from .runtime_config import configured_features, default_site, default_user
from .service import FernService


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description=("Create managed-catalog rows for document events "
                     "imported before the catalog existed (Phase 15).")
    )
    parser.add_argument("--site", default=default_site())
    parser.add_argument("--user", default=default_user())
    parser.add_argument("--db")
    parser.add_argument("--config", default="fern.toml",
                        help="fern.toml with [documents] enabled = true, or "
                             "set FERNME_MANAGED_DOCUMENTS=true")
    parser.add_argument("--confirm", action="store_true",
                        help="write catalog rows (default is a dry run)")
    parser.add_argument("--now", type=float, default=0.0)
    args = parser.parse_args(argv)

    cfg = configured_features(args.config)
    service = (FernService(db_path=args.db, cfg=cfg) if args.db
              else FernService(cfg=cfg))
    report = service.backfill_documents(
        args.site, args.user, dry_run=not args.confirm, now=args.now)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
