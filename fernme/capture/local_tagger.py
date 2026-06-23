"""local — extract tags from *text* with 0 API tokens, using your own machine.

Two modes:

  rules  (default, works today, 0 dependencies): a deterministic keyword/phrase
         catalog maps text -> tags. Lower recall than a model, but truly free and
         reproducible. Catalog is extendable via a JSON file.

  model  (opt-in, install later): a small local model via Ollama
         (http://localhost:11434) reads the text and proposes tags. Still 0
         *billed* tokens — it runs on your CPU/GPU. Falls back to `rules` if the
         endpoint is unreachable, so it never silently does nothing.
"""
from __future__ import annotations
import json
import re
import urllib.request
from typing import Dict, List

from .base import BaseAdapter
from ..safety import sanitize_tags

# Starter catalog: lowercase phrase -> tag. Intentionally small + high-precision.
# Extend per user via a JSON file ({"phrase": "namespace:value", ...}).
_CATALOG = {
    "concise": "pref:concise", "terse": "pref:concise", "to the point": "pref:concise",
    "short answer": "pref:concise", "no fluff": "pref:concise",
    "step by step": "pref:step-by-step", "detailed": "pref:detailed",
    "dark mode": "pref:dark-mode", "light mode": "pref:light-mode",
    "vegetarian": "diet:vegetarian", "vegan": "diet:vegan",
    "oat milk": "likes:oat-milk", "espresso": "likes:espresso",
    "python": "topic:python", "rust": "topic:rust", "javascript": "topic:web",
    "machine learning": "topic:ml", "startup": "topic:startup",
}
_NEG = re.compile(r"\b(don'?t like|hate|avoid|never|no )\b")
_WORD = re.compile(r"[a-z][a-z0-9\- ]+")


class LocalTaggerAdapter(BaseAdapter):
    name = "local"
    cost_label = "0 API tokens — runs on your own CPU/GPU (rules now, model later)"
    cost_tokens = 0
    reads_text = True
    needs = "nothing for rules mode; Ollama + a model for model mode"

    def __init__(self, mode: str = "rules", model: str = "hermes3",
                 endpoint: str = "http://localhost:11434", catalog: Dict = None):
        self.mode = mode
        self.model = model
        self.endpoint = endpoint.rstrip("/")
        self.catalog = dict(_CATALOG)
        if catalog:
            self.catalog.update(catalog)
        self.last_mode_used = mode

    # ---- rules mode: deterministic keyword match -------------------------
    def _rules(self, text: str) -> List[str]:
        low = " " + text.lower() + " "
        negated = bool(_NEG.search(low))
        out: List[str] = []
        for phrase, tag in self.catalog.items():
            if phrase in low:
                out.append(("!" + tag) if (negated and tag.startswith("likes:")) else tag)
        return out

    # ---- model mode: local Ollama, no billed tokens ----------------------
    def _model(self, text: str) -> List[str]:
        prompt = ("Extract durable user preferences/facts from the text as short "
                  "namespace:value tokens (e.g. pref:concise, topic:python). "
                  "Return only a comma-separated list.\nTEXT: " + text)
        body = json.dumps({"model": self.model, "prompt": prompt,
                           "stream": False}).encode()
        req = urllib.request.Request(self.endpoint + "/api/generate", data=body,
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as r:
            resp = json.loads(r.read().decode())
        raw = (resp.get("response") or "").replace("\n", ",")
        return [t for t in (s.strip() for s in raw.split(",")) if ":" in t]

    def extract(self, event: Dict) -> List[str]:
        text = event.get("text")
        if not text:
            return []
        if self.mode == "model":
            try:
                self.last_mode_used = "model"
                return sanitize_tags(self._model(text))
            except Exception:
                self.last_mode_used = "rules (model unreachable)"  # honest fallback
        else:
            self.last_mode_used = "rules"
        return sanitize_tags(self._rules(text))
