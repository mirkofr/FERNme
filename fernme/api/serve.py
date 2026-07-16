"""Command-line launcher for the local FERNme REST and graph UI."""
from __future__ import annotations

import argparse
import os
import sys
import threading
import webbrowser


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="fernme-ui",
        description="Start the local FERNme REST API and graph UI.",
    )
    parser.add_argument("--db", help="SQLite database path. Overrides FERNME_DB.")
    parser.add_argument("--site", help="Default site/context. Overrides FERNME_SITE.")
    parser.add_argument("--user", help="Default local user. Overrides FERNME_USER.")
    parser.add_argument("--host", default="127.0.0.1", help="Bind host. Default: 127.0.0.1.")
    parser.add_argument("--port", type=int, default=8077, help="Bind port. Default: 8077.")
    parser.add_argument("--path", default="/ui/graph", help="UI path to open. Default: /ui/graph.")
    parser.add_argument("--no-open", action="store_true", help="Start the server without opening a browser.")
    parser.add_argument("--reload", action="store_true", help="Enable uvicorn reload for local development.")
    return parser


def apply_env(args: argparse.Namespace) -> None:
    if args.db:
        os.environ["FERNME_DB"] = args.db
    if args.site:
        os.environ["FERNME_SITE"] = args.site
    if args.user:
        os.environ["FERNME_USER"] = args.user


def target_url(args: argparse.Namespace) -> str:
    path = args.path if str(args.path).startswith("/") else f"/{args.path}"
    return f"http://{args.host}:{args.port}{path}"


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    apply_env(args)

    try:
        import uvicorn
    except ModuleNotFoundError:
        print(
            'FERNme UI dependencies are missing. Install with: python -m pip install "fernme[ui]"',
            file=sys.stderr,
        )
        return 2

    if not args.no_open:
        threading.Timer(0.75, webbrowser.open, args=(target_url(args),)).start()
    uvicorn.run("fernme.api.rest:app", host=args.host, port=args.port, reload=args.reload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
