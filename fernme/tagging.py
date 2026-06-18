"""Pluggable taggers — the LLM enrichment layer, kept optional and behind one
interface so the engine core never changes.

  DeterministicTagger : catalog/payload tags only. No LLM. The default. Key-less.
  LLMTagger           : turns free text into attributes via a caller-supplied
                        `llm_fn(prompt)->str`. Constrained to a controlled
                        vocabulary when provided (the real consistency lever).
                        EXPERIMENTAL until run against a real model.

The engine stays the source of truth; a tagger only proposes attribute tokens,
which are then sanitized and fed through the normal (no-LLM) write path."""
from __future__ import annotations
from typing import Callable, List, Optional, Sequence
from .safety import sanitize_tags


class DeterministicTagger:
    """No LLM: just whatever the event/catalog already carries."""
    def tag(self, text: str, payload: dict) -> List[str]:
        return list(payload.get("tags", []))


class LLMTagger:
    """Wraps a user-supplied LLM call. `llm_fn` takes a prompt and returns a
    comma/space-separated list of attribute tokens. We never trust its output:
    it is sanitized and (optionally) filtered to a fixed vocabulary."""
    def __init__(self, llm_fn: Callable[[str], str],
                 vocabulary: Optional[Sequence[str]] = None):
        self.llm_fn = llm_fn
        self.vocab = set(vocabulary) if vocabulary else None
        self.calls = 0

    def _prompt(self, text: str) -> str:
        vocab = (f"Choose only from this vocabulary: {sorted(self.vocab)}.\n"
                 if self.vocab else "Use short snake_case attribute tokens.\n")
        return ("Extract durable user preferences as attribute tokens from the "
                "text below. Return a comma-separated list, nothing else.\n"
                + vocab + f"TEXT: {text}")

    def tag(self, text: str, payload: dict) -> List[str]:
        self.calls += 1
        raw = self.llm_fn(self._prompt(text)) or ""
        toks = sanitize_tags([t for t in raw.replace("\n", ",").split(",")])
        if self.vocab is not None:
            toks = [t for t in toks if t in self.vocab]
        return toks
