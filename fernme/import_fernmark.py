"""CLI for consented, deterministic FERNmark document import and forgetting."""
from __future__ import annotations

import argparse
import json

from .runtime_config import default_site, default_user
from .service import FernService


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Import validated FERNmark envelopes into FERNme."
    )
    parser.add_argument("source", nargs="?", help="envelope or directory")
    parser.add_argument("--site", default=default_site())
    parser.add_argument("--user", default=default_user())
    parser.add_argument("--db")
    parser.add_argument("--config", default="fern.toml")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--forget", metavar="SHA256")
    parser.add_argument("--max-bytes", type=int)
    parser.add_argument("--now", type=float, default=0.0)
    args = parser.parse_args(argv)

    if bool(args.source) == bool(args.forget):
        parser.error("provide exactly one envelope source or --forget SHA256")

    service = FernService(db_path=args.db) if args.db else FernService()
    if args.forget:
        report = service.forget_document(
            args.site, args.user, args.forget, ts=args.now)
    else:
        report = service.import_fernmark(
            args.site,
            args.user,
            args.source,
            dry_run=args.dry_run,
            config_path=args.config,
            max_bytes=args.max_bytes,
            now=args.now,
        )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
