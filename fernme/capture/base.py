"""Capture adapters — the *perception* layer that sits above the 0-LLM engine.

The FERNme write (`service.observe`) is pure graph arithmetic: 0 LLM tokens,
always. What differs per deployment is only *how tags are produced* from
experience. Each adapter is one way to turn an event into tags, and carries an
honest `cost_label` / `cost_tokens` so an installer can tell the user exactly
what it will cost — no hidden LLM calls.

  signal   structured events (command/file/git/app/calendar) -> rules. 0 tokens.
  local    text -> local keyword rules, or a small local model (Ollama). 0 API
           tokens; uses your own CPU/GPU.
  agent    the host agent (Claude Cowork, Codex, ...) emits a tiny tag line as a
           byproduct of the reply it is already writing. ~20-40 output tokens,
           no *separate* LLM call.

Adapters only PROPOSE tags. They are sanitized and written through the normal
no-LLM path, so the engine stays the single source of truth.
"""
from __future__ import annotations
from typing import Dict, List

# An "event" is a plain dict. Conventional keys:
#   kind : str  -- "chat" | "command" | "file" | "git" | "app" | "calendar"
#   text : str  -- free text (for chat / local tagger)
#   ...  : adapter-specific fields (cmd, path, repo, msg, name, title, ...)


class BaseAdapter:
    """One way to turn an event into proposed tags.

    Subclasses set the class attributes and implement `extract`. `cost_tokens`
    is the rough per-write LLM-token cost this adapter *causes* (0 means it
    spends no model tokens at all)."""

    name: str = "base"
    cost_label: str = ""
    cost_tokens: int = 0          # rough billed tokens caused per write
    reads_text: bool = False      # whether it consumes event["text"]
    needs: str = "nothing"        # human note: what must be present to use it

    def extract(self, event: Dict) -> List[str]:
        raise NotImplementedError

    # convenience so adapters are printable in the installer table
    def info(self) -> Dict:
        return {
            "name": self.name,
            "cost_label": self.cost_label,
            "cost_tokens": self.cost_tokens,
            "needs": self.needs,
        }
