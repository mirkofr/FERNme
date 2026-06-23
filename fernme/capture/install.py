"""Installer / picker for FERNme capture methods.

Prints a plain cost table so the user sees exactly what each method does and how
many tokens it costs, then writes `fern.toml`. Runnable two ways:

    python -m fernme.capture.install                 # interactive picker
    python -m fernme.capture.install --methods agent,signal --out fern.toml
    python -m fernme.capture.install --show          # just print the table
"""
from __future__ import annotations
import argparse
import sys
from typing import List

from .base import BaseAdapter
from . import REGISTRY, VALID, default_config, write_config

# stable display order + one-line "captures" note per method
_ORDER = ["agent", "signal", "local"]
_CAPTURES = {
    "agent": "full chat meaning (host agent emits tags)",
    "signal": "behavior only: commands, files, git, apps, calendar",
    "local": "full chat meaning, on your own machine",
}


def _adapter(name: str) -> BaseAdapter:
    return REGISTRY[name]()


def cost_table() -> str:
    rows = [("METHOD", "TOKEN COST", "CAPTURES", "NEEDS")]
    for name in _ORDER:
        a = _adapter(name)
        cost = "0 (free)" if a.cost_tokens == 0 else "~%d/write" % a.cost_tokens
        rows.append((name, cost, _CAPTURES[name], a.needs))
    w = [max(len(r[i]) for r in rows) for i in range(4)]
    line = lambda r: "  ".join(r[i].ljust(w[i]) for i in range(4))
    sep = "  ".join("-" * w[i] for i in range(4))
    out = [line(rows[0]), sep] + [line(r) for r in rows[1:]]
    note = ("\nNotes: 'agent' also costs ~25-50 tokens per *read* (the memory card "
            "injected into the\nagent's context). 'signal' and 'local' write only "
            "— no read-side token cost. Zero-token\nmethods trade recall for cost: "
            "they catch less nuance than a model would.")
    return "\n".join(out) + "\n" + note


def _interactive() -> List[str]:
    print("\nFERNme — choose how memory gets written.\n")
    print(cost_table())
    print("\nYou can pick more than one (they stack). Example: agent,signal\n")
    raw = input("Methods [agent,signal]: ").strip() or "agent,signal"
    chosen = [m.strip() for m in raw.split(",") if m.strip() in VALID]
    return chosen or ["agent", "signal"]


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Install FERNme capture methods.")
    p.add_argument("--methods", help="comma list: %s" % ",".join(_ORDER))
    p.add_argument("--out", default="fern.toml", help="config path to write")
    p.add_argument("--show", action="store_true", help="print the cost table and exit")
    args = p.parse_args(argv)

    if args.show:
        print(cost_table())
        return 0

    if args.methods:
        chosen = [m.strip() for m in args.methods.split(",") if m.strip() in VALID]
        bad = [m.strip() for m in args.methods.split(",") if m.strip() not in VALID]
        if bad:
            print("ignored unknown methods: %s (valid: %s)" % (bad, ", ".join(VALID)),
                  file=sys.stderr)
        if not chosen:
            print("no valid methods given", file=sys.stderr)
            return 2
    else:
        chosen = _interactive()

    cfg = default_config(active=chosen)
    path = write_config(cfg, args.out)
    print("\nWrote %s with active methods: %s" % (path, ", ".join(chosen)))
    total = sum(_adapter(n).cost_tokens for n in chosen)
    print("Estimated write cost: %s tokens%s" % (
        total, " (free)" if total == 0 else " per write"))
    if "local" in chosen:
        print("local: starts in rules mode (0 tokens). Install Ollama + a model and "
              "set mode=\"model\" in fern.toml to upgrade.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
