"""Read/write `fern.toml` — which capture adapters are active and their options.

Dependency-free: a tiny targeted TOML reader/writer for our small, known schema
(so it works on any Python with no `tomli`/`tomllib` requirement). Shape:

    [capture]
    active = ["agent", "signal"]

    [capture.local]
    mode = "rules"          # rules | model
    model = "hermes3"
    endpoint = "http://localhost:11434"

    [capture.agent]
    marker = "FERN_TAGS:"
"""
from __future__ import annotations
import os
import re
from typing import Dict, List

DEFAULT_PATH = "fern.toml"
VALID = ("signal", "local", "agent", "document")


def default_config(active: List[str] = None) -> Dict:
    return {
        "active": list(active) if active else ["agent", "signal"],
        "local": {"mode": "rules", "model": "hermes3",
                  "endpoint": "http://localhost:11434"},
        "agent": {"marker": "FERN_TAGS:"},
    }


_ACTIVE = re.compile(r'^\s*active\s*=\s*\[(.*?)\]', re.MULTILINE)
_SECTION = re.compile(r'^\s*\[capture\.(\w+)\]\s*$')
_KV = re.compile(r'^\s*(\w+)\s*=\s*"(.*?)"\s*$')


def load_config(path: str = DEFAULT_PATH) -> Dict:
    """Parse fern.toml; missing file -> default config."""
    cfg = default_config()
    if not os.path.exists(path):
        return cfg
    with open(path, "r", encoding="utf-8") as f:
        text = f.read()
    m = _ACTIVE.search(text)
    if m:
        items = [s.strip().strip('"').strip("'") for s in m.group(1).split(",")]
        cfg["active"] = [s for s in items if s in VALID]
    section = None
    for line in text.splitlines():
        sm = _SECTION.match(line)
        if sm:
            section = sm.group(1)
            cfg.setdefault(section, {})
            continue
        if section:
            kv = _KV.match(line)
            if kv:
                cfg[section][kv.group(1)] = kv.group(2)
    return cfg


def write_config(cfg: Dict, path: str = DEFAULT_PATH) -> str:
    active = ", ".join('"%s"' % a for a in cfg.get("active", []))
    lines = ["# FERNme capture config — which perception adapters are active.",
             "# The engine write is always 0-LLM; only tag *production* differs.",
             "", "[capture]", "active = [%s]" % active, ""]
    for sec in ("local", "agent"):
        opts = cfg.get(sec)
        if not opts:
            continue
        lines.append("[capture.%s]" % sec)
        for k, v in opts.items():
            lines.append('%s = "%s"' % (k, v))
        lines.append("")
    out = "\n".join(lines)
    with open(path, "w", encoding="utf-8") as f:
        f.write(out)
    return path
