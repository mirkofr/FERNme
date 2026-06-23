"""signal — truly 0-token capture from *structured events*, not conversation.

A command you run, a file you open, a git commit, an app you launch, a calendar
entry: each is mapped to tags by a deterministic rule table. No model, no API,
no tokens. The honest catch: this captures your *behavior*, not the *meaning* of
what you say. High precision, by design — it only emits a tag when a rule
matches, so it never guesses.
"""
from __future__ import annotations
import os
import re
from typing import Dict, List

from .base import BaseAdapter

# first token of a shell command -> tool tag
_CMD_TOOL = {
    "git": "tool:git", "python": "tool:python", "python3": "tool:python",
    "pip": "tool:python", "node": "tool:node", "npm": "tool:node",
    "pnpm": "tool:node", "yarn": "tool:node", "docker": "tool:docker",
    "kubectl": "tool:k8s", "cargo": "tool:rust", "go": "tool:go",
    "make": "tool:make", "ssh": "tool:ssh", "curl": "tool:http",
    "psql": "tool:postgres", "sqlite3": "tool:sqlite", "blender": "tool:blender",
}
# file extension -> topic tag
_EXT_TOPIC = {
    ".py": "topic:python", ".ipynb": "topic:python",
    ".js": "topic:web", ".ts": "topic:web", ".jsx": "topic:web",
    ".tsx": "topic:web", ".html": "topic:web", ".css": "topic:web",
    ".md": "topic:writing", ".txt": "topic:writing", ".docx": "topic:writing",
    ".csv": "topic:data", ".xlsx": "topic:data", ".parquet": "topic:data",
    ".sql": "topic:data", ".rs": "topic:rust", ".go": "topic:go",
    ".tex": "topic:writing", ".blend": "topic:3d",
}
# app name (lowercased) -> tag
_APP_TAG = {
    "blender": "tool:blender", "code": "tool:vscode", "vscode": "tool:vscode",
    "obsidian": "tool:obsidian", "excel": "tool:excel", "word": "tool:writing",
    "terminal": "habit:cli", "iterm": "habit:cli", "chrome": "tool:browser",
}
# conventional-commit prefix -> activity tag
_COMMIT_TYPE = {
    "feat": "activity:feature", "fix": "activity:bugfix", "docs": "activity:docs",
    "test": "activity:testing", "refactor": "activity:refactor",
    "chore": "activity:chore", "perf": "activity:perf",
}
_SLUG = re.compile(r"[^a-z0-9]+")


def _slug(s: str) -> str:
    return _SLUG.sub("-", s.strip().lower()).strip("-")


class SignalAdapter(BaseAdapter):
    name = "signal"
    cost_label = "0 tokens — deterministic rules over structured events"
    cost_tokens = 0
    reads_text = False
    needs = "nothing (captures behavior, not chat meaning)"

    def extract(self, event: Dict) -> List[str]:
        kind = event.get("kind")
        if kind == "command":
            return self._command(event)
        if kind == "file":
            return self._file(event)
        if kind == "git":
            return self._git(event)
        if kind == "app":
            return self._app(event)
        if kind == "calendar":
            return self._calendar(event)
        return []

    def _command(self, e: Dict) -> List[str]:
        cmd = (e.get("cmd") or "").strip()
        if not cmd:
            return []
        tags = ["habit:cli"]
        head = cmd.split()[0].split("/")[-1]
        if head in _CMD_TOOL:
            tags.append(_CMD_TOOL[head])
        return tags

    def _file(self, e: Dict) -> List[str]:
        path = e.get("path") or ""
        if not path:
            return []
        tags: List[str] = []
        ext = os.path.splitext(path)[1].lower()
        if ext in _EXT_TOPIC:
            tags.append(_EXT_TOPIC[ext])
        # parent folder -> project tag (deterministic; only the immediate folder)
        folder = os.path.basename(os.path.dirname(path.replace("\\", "/")))
        if folder:
            tags.append("project:" + _slug(folder))
        return tags

    def _git(self, e: Dict) -> List[str]:
        tags = ["habit:commits"]
        repo = e.get("repo")
        if repo:
            tags.append("project:" + _slug(repo))
        msg = (e.get("msg") or "").strip().lower()
        prefix = msg.split(":", 1)[0].split("(", 1)[0]
        if prefix in _COMMIT_TYPE:
            tags.append(_COMMIT_TYPE[prefix])
        return tags

    def _app(self, e: Dict) -> List[str]:
        name = (e.get("name") or "").strip().lower()
        return [_APP_TAG[name]] if name in _APP_TAG else []

    def _calendar(self, e: Dict) -> List[str]:
        title = (e.get("title") or "").lower()
        if not title:
            return []
        if any(w in title for w in ("1:1", "1-1", "sync", "standup", "meeting")):
            return ["habit:meetings"]
        return []
