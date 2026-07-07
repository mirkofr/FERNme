"""CLI for deterministic Obsidian vault import."""
from __future__ import annotations

import argparse
import json

from .service import FernService


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("vault")
    parser.add_argument("--site", required=True)
    parser.add_argument("--user", required=True)
    parser.add_argument("--db")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--include", action="append", default=[])
    parser.add_argument("--exclude", action="append", default=[])
    parser.add_argument("--max-notes", type=int)
    parser.add_argument("--now", type=float, default=0.0)
    ns = parser.parse_args()

    svc = FernService(db_path=ns.db) if ns.db else FernService()
    report = svc.import_obsidian(
        ns.site,
        ns.user,
        ns.vault,
        dry_run=ns.dry_run,
        include=ns.include or None,
        exclude=ns.exclude or None,
        max_notes=ns.max_notes,
        now=ns.now,
    )
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
