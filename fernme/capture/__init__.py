"""fernme.capture — the pluggable *perception* layer above the 0-LLM engine.

Pick how memory gets written without touching the engine. Four adapters, each
with an honest token-cost label:

    signal   structured events -> rules            0 tokens
    local    text -> local rules or local model    0 API tokens (your CPU/GPU)
    agent    host agent emits a tag line           ~20-40 tokens, no extra call
    document validated FERNmark metadata           0 tokens

Typical use:

    from fernme.service import FernService
    from fernme.store.sqlite_store import SQLiteStore
    from fernme.capture import load_pipeline

    svc = FernService(store=SQLiteStore("memory.db"))
    svc.store.set_consent("demo.com", "elena", True)
    pipe = load_pipeline(svc, "demo.com", "elena", "fern.toml")
    pipe.ingest({"kind": "chat", "text": "keep it concise",
                 "tags": ["pref:concise"]})
"""
from __future__ import annotations
from typing import Dict, List

from .base import BaseAdapter
from .signal_hooks import SignalAdapter
from .local_tagger import LocalTaggerAdapter
from .agent_byproduct import AgentByproductAdapter
from .fernmark_documents import DocumentAdapter
from .config import load_config, write_config, default_config, VALID
from .pipeline import CapturePipeline
from .extractors import extract_structured

REGISTRY = {
    "signal": SignalAdapter,
    "local": LocalTaggerAdapter,
    "agent": AgentByproductAdapter,
    "document": DocumentAdapter,
}


def build_adapters(cfg: Dict) -> List[BaseAdapter]:
    """Instantiate the active adapters from a parsed config dict."""
    out: List[BaseAdapter] = []
    for name in cfg.get("active", []):
        cls = REGISTRY.get(name)
        if cls is None:
            continue
        opts = dict(cfg.get(name, {}))
        if name == "local":
            out.append(LocalTaggerAdapter(
                mode=opts.get("mode", "rules"),
                model=opts.get("model", "hermes3"),
                endpoint=opts.get("endpoint", "http://localhost:11434")))
        elif name == "agent":
            out.append(AgentByproductAdapter(marker=opts.get("marker", "FERN_TAGS:")))
        else:
            out.append(cls())
    return out


def load_pipeline(svc, site: str, user: str, path: str = "fern.toml") -> CapturePipeline:
    cfg = load_config(path)
    return CapturePipeline(svc, site, user, build_adapters(cfg))


__all__ = [
    "BaseAdapter", "SignalAdapter", "LocalTaggerAdapter", "AgentByproductAdapter",
    "DocumentAdapter",
    "CapturePipeline", "REGISTRY", "VALID",
    "build_adapters", "load_pipeline", "load_config", "write_config",
    "default_config", "extract_structured",
]
