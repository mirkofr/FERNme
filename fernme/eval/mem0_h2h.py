"""FERNme vs Mem0 head-to-head on the unified synthetic harness scenarios.

Owner-run. The Mem0 backend makes real LLM + embedding API calls and needs
``pip install mem0ai`` plus ``OPENAI_API_KEY`` (or a ``--mem0-config`` JSON for
another provider). Nothing here runs in CI against a real API.

    python -m fernme.eval.mem0_h2h --check                  # preflight, no API calls
    python -m fernme.eval.mem0_h2h --backend stub           # plumbing test, no API calls
    python -m fernme.eval.mem0_h2h --backend mem0 --seeds 3 --json reports/mem0_h2h.json

Fairness contract (read before quoting results):
- Both systems receive the same events in the same order: the event's tags,
  rendered as a plain-English sentence, plus the event's free text. FERNme
  receives the tags natively; Mem0 receives the sentence.
- Both are scored on the same hidden answer keys with the same recall@k /
  precision@k / stale-rate definitions as ``fernme.eval.harness``.
- Mem0 returns prose memories, not tags. They are mapped back to attributes
  lexically: an attribute counts when its humanized value (``jasmine tea``)
  appears in a returned memory and is not preceded by a negation cue in that
  memory ("no longer", "stopped", "not", ...). This mapper is deliberately
  simple and can under- or over-credit Mem0; results must be reported with
  this caveat.
- Scenarios are synthetic. Results describe these fixtures only, not real users.
- ``fragmented_entity`` and ``outcome`` regimes are excluded: they exercise
  FERNme-only mechanisms (entity setup, outcome feedback) with no Mem0 analogue.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import tempfile
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from ..config import DEFAULT
from ..retrieve.card import estimate_tokens
from . import harness as H

REGIMES = ("static", "abrupt_drift", "gradual_drift", "staleness", "contextual")
BASELINES = ("fern_pure", "recency", "frequency", "bm25")
MEM0_USER = "fictional-h2h-user"

_NS_PHRASE = {
    "pref": "prefers", "style": "style is", "size": "wears size", "food": "eats",
    "drink": "drinks", "brand": "shops at", "pace": "pace is", "topic": "asked about",
    "person": "mentioned", "project": "works on", "fast": "currently", "slow": "long-term",
    "ctx": "context", "org": "is connected to",
}
_NEGATION_RE = re.compile(
    r"\b(no longer|not|never|stopped|doesn't|does not|don't|do not|dislikes?|"
    r"avoids?|used to|previously|formerly|switched (?:away )?from|replaced)\b")

# A negation cue only applies within its own clause ("no longer drinks X and now
# prefers Y" must still credit Y).
_CLAUSE_RE = re.compile(r"[.;,:]|\b(?:and|but|while|whereas|now|instead|currently)\b")


def humanize_value(attr: str) -> str:
    """``pref:jasmine-tea`` -> ``jasmine tea`` (value only, lowercase)."""
    value = attr.split(":", 1)[-1].lstrip("!")
    return value.replace("-", " ").replace("_", " ").strip().lower()


def event_sentence(ev: H.HarnessEvent) -> str:
    """Render one harness event as the sentence Mem0 ingests."""
    parts = []
    for tag in ev.tags:
        ns = tag.split(":", 1)[0].lstrip("!") if ":" in tag else "note"
        verb = _NS_PHRASE.get(ns, "noted")
        neg = "does not like " if tag.startswith("!") else ""
        parts.append(f"{neg}{verb} {humanize_value(tag)}".strip())
    facts = "; ".join(parts) if parts else "no specific signal"
    return f"Day {int(ev.ts)}: during a {ev.kind}, the user {facts}. {ev.text}".strip()


def probe_query(probe: H.Probe) -> str:
    ctx = ", ".join(humanize_value(c) for c in probe.context)
    return f"{probe.query} Current context: {ctx}." if ctx else probe.query


def memories_to_attrs(memories: Sequence[str], universe: Sequence[str], k: int) -> List[str]:
    """Map ranked prose memories to ranked attributes (lexical, negation-aware)."""
    # Longest phrases first so "mint tea" is not shadowed by a shorter overlap.
    candidates = sorted(set(universe), key=lambda a: -len(humanize_value(a)))
    out: List[str] = []
    for mem in memories:
        text = mem.lower()
        hits = []
        for attr in candidates:
            phrase = humanize_value(attr)
            if not phrase:
                continue
            m = re.search(rf"\b{re.escape(phrase)}\b", text)
            if not m:
                continue
            bounds = [b.end() for b in _CLAUSE_RE.finditer(text, 0, m.start())]
            prefix = text[(bounds[-1] if bounds else 0):m.start()]
            if _NEGATION_RE.search(prefix):
                continue
            hits.append((m.start(), attr))
        for _pos, attr in sorted(hits):
            if attr not in out:
                out.append(attr)
            if len(out) >= k:
                return out
    return out


# ---------------------------------------------------------------- backends

@dataclass
class BackendRun:
    memories: List[str]
    llm_calls: int
    embed_calls: int
    write_seconds: float
    read_seconds: float


class StubBackend:
    """Deterministic keyword-overlap memory. Plumbing test only; not Mem0."""

    label = "stub (plumbing only)"

    def run(self, events: Sequence[H.HarnessEvent], query: str, k: int) -> BackendRun:
        t0 = time.perf_counter()
        store = [event_sentence(ev) for ev in events]
        t1 = time.perf_counter()
        q = set(H._terms(query))
        ranked = sorted(enumerate(store),
                        key=lambda it: (-len(q & set(H._terms(it[1]))), -it[0]))
        mems = [s for _i, s in ranked[:k]]
        return BackendRun(mems, 0, 0, t1 - t0, time.perf_counter() - t1)


class Mem0Backend:
    """Real Mem0 OSS ``Memory``; one isolated collection per scenario run."""

    label = "Mem0 (LLM)"

    def __init__(self, config: Optional[Dict] = None, llm_model: str = "gpt-4.1-mini",
                 embedder_model: str = "text-embedding-3-small", search_k: int = 10):
        # Keep the benchmark's synthetic traffic out of Mem0's product telemetry.
        os.environ.setdefault("MEM0_TELEMETRY", "False")
        from mem0 import Memory  # noqa: F401  (import error surfaces early)
        self._config = config
        self._llm_model = llm_model
        self._embedder_model = embedder_model
        self._search_k = search_k

    def _build(self, workdir: str):
        from mem0 import Memory
        if self._config is not None:
            cfg = json.loads(json.dumps(self._config))
        else:
            cfg = {
                "llm": {"provider": "openai", "config": {"model": self._llm_model,
                                                          "temperature": 0}},
                "embedder": {"provider": "openai",
                             "config": {"model": self._embedder_model}},
                "vector_store": {"provider": "qdrant", "config": {}},
            }
        vs = cfg.setdefault("vector_store", {"provider": "qdrant", "config": {}})
        vs.setdefault("config", {})
        if vs.get("provider", "qdrant") == "qdrant":
            vs["config"]["path"] = os.path.join(workdir, "qdrant")
            vs["config"]["collection_name"] = f"fernme_h2h_{uuid.uuid4().hex[:10]}"
        cfg["history_db_path"] = os.path.join(workdir, "history.db")
        return Memory.from_config(cfg)

    @staticmethod
    def _count(obj, attr: str, counter: Dict[str, int], key: str) -> None:
        fn = getattr(obj, attr, None) if obj is not None else None
        if not callable(fn):
            return

        def wrapped(*a, **kw):
            counter[key] += 1
            return fn(*a, **kw)
        setattr(obj, attr, wrapped)

    def run(self, events: Sequence[H.HarnessEvent], query: str, k: int) -> BackendRun:
        counts = {"llm": 0, "embed": 0}
        with tempfile.TemporaryDirectory(prefix="fernme_mem0_h2h_") as workdir:
            m = self._build(workdir)
            self._count(getattr(m, "llm", None), "generate_response", counts, "llm")
            self._count(getattr(m, "embedding_model", None), "embed", counts, "embed")
            self._count(getattr(m, "embedding_model", None), "embed_batch", counts, "embed")
            t0 = time.perf_counter()
            for ev in events:
                m.add([{"role": "user", "content": event_sentence(ev)}], user_id=MEM0_USER)
            t1 = time.perf_counter()
            res = m.search(query, top_k=self._search_k, filters={"user_id": MEM0_USER})
            t2 = time.perf_counter()
        items = res.get("results", res) if isinstance(res, dict) else res
        mems = [str(r.get("memory", "")) for r in items or [] if isinstance(r, dict)]
        return BackendRun(mems, counts["llm"], counts["embed"], t1 - t0, t2 - t1)


# ---------------------------------------------------------------- runner

def _scenarios(seed: int) -> List[H.Scenario]:
    return [s for s in H.build_scenarios(seed) if s.name in REGIMES]


def plan(seeds: int) -> Dict:
    scen = [s for seed in range(seeds) for s in _scenarios(seed)]
    adds = sum(len(s.events) for s in scen)
    return {"scenario_runs": len(scen), "mem0_add_calls": adds,
            "mem0_search_calls": sum(len(s.probes) for s in scen)}


def check(seeds: int, env: Optional[Dict[str, str]] = None) -> Dict:
    """Preflight without any network/API call."""
    env = os.environ if env is None else env
    report = {
        "mem0ai_installed": importlib.util.find_spec("mem0") is not None,
        "openai_api_key_set": bool(env.get("OPENAI_API_KEY")),
        **plan(seeds),
    }
    report["ready"] = report["mem0ai_installed"] and report["openai_api_key_set"]
    return report


def run(backend, seeds: int = 3, k: int = 5,
        progress: Optional[Callable[[str], None]] = None) -> Dict:
    rows: List[Dict] = []
    for seed in range(seeds):
        for scenario in _scenarios(seed):
            cfg = H._scenario_cfg(DEFAULT, scenario.cfg_overrides)
            universe = sorted({t for ev in scenario.events for t in ev.tags
                               if not t.startswith("ctx:")})
            for probe in scenario.probes:
                for method in BASELINES:
                    r = H._run_method(method, scenario, probe, cfg, k)
                    rows.append({"seed": seed, **r.as_dict(),
                                 "write_llm_calls": 0.0, "embed_calls": 0.0})
                if progress:
                    progress(f"seed {seed} {scenario.name}: {backend.label} ...")
                br = backend.run(scenario.events, probe_query(probe), k)
                pred = memories_to_attrs(br.memories, universe, k)
                injected = " ".join(br.memories[:k])
                scored = H._score_prediction("mem0", scenario.name, pred,
                                             estimate_tokens(injected) if injected else 0,
                                             br.llm_calls, probe, k)
                rows.append({"seed": seed, **scored.as_dict(),
                             "write_llm_calls": float(br.llm_calls),
                             "embed_calls": float(br.embed_calls),
                             "write_seconds": br.write_seconds,
                             "read_seconds": br.read_seconds,
                             "events": len(scenario.events),
                             "raw_memories": br.memories[:k]})
    methods = BASELINES + ("mem0",)
    summary: Dict = {}
    for regime in REGIMES:
        summary[regime] = {}
        for method in methods:
            sel = [r for r in rows if r["regime"] == regime and r["method"] == method]
            summary[regime][method] = {
                m: {"mean": round(H._mean([float(r[m]) for r in sel]), 6),
                    "sd": round(H._sd([float(r[m]) for r in sel]), 6)}
                for m in ("recall_at_k", "precision_at_k", "stale_recall_rate",
                          "token_estimate", "llm_calls")
            }
    return {"mode": "synthetic-mem0-head-to-head", "schema_version": 1,
            "backend": backend.label, "seeds": list(range(seeds)), "k": k,
            "regimes": list(REGIMES), "methods": list(methods),
            "caveats": [
                "Synthetic fixtures with hidden answer keys; not real users.",
                "Mem0 prose memories are mapped to attributes lexically with a "
                "negation filter; the mapper can under- or over-credit Mem0.",
                "llm_calls for Mem0 counts LLM calls made during add() for the "
                "whole scenario; FERNme and the heuristics make none.",
            ],
            "summary": summary, "rows": rows}


def format_table(report: Dict) -> str:
    labels = dict(H.METHOD_LABELS, mem0=report["backend"])
    lines = [f"FERNme vs {report['backend']} -- SYNTHETIC fixtures, k={report['k']}, "
             f"seeds={len(report['seeds'])}", ""]
    lines.append(f"{'regime':<14}{'method':<22}{'recall@k':>10}{'prec@k':>9}"
                 f"{'stale':>8}{'tokens':>9}{'LLM calls':>11}")
    for regime in report["regimes"]:
        for method in report["methods"]:
            s = report["summary"][regime][method]
            lines.append(f"{regime:<14}{labels[method]:<22}"
                         f"{s['recall_at_k']['mean']:>10.3f}{s['precision_at_k']['mean']:>9.3f}"
                         f"{s['stale_recall_rate']['mean']:>8.3f}"
                         f"{s['token_estimate']['mean']:>9.1f}{s['llm_calls']['mean']:>11.1f}")
        lines.append("")
    return "\n".join(lines)


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--check", action="store_true", help="preflight only; no API calls")
    ap.add_argument("--backend", choices=("stub", "mem0"), default="stub")
    ap.add_argument("--seeds", type=int, default=3)
    ap.add_argument("--k", type=int, default=5)
    ap.add_argument("--llm-model", default="gpt-4.1-mini")
    ap.add_argument("--embedder-model", default="text-embedding-3-small")
    ap.add_argument("--mem0-config", help="JSON file passed to mem0 Memory.from_config")
    ap.add_argument("--json", help="write the full report here")
    ns = ap.parse_args(argv)

    if ns.check:
        rep = check(ns.seeds)
        print(json.dumps(rep, indent=2))
        if not rep["ready"]:
            print("Not ready: pip install mem0ai and set OPENAI_API_KEY "
                  "(or pass --mem0-config for another provider).")
        return 0 if rep["ready"] else 1

    if ns.backend == "mem0":
        rep = check(ns.seeds)
        if not rep["mem0ai_installed"]:
            raise SystemExit("mem0ai is not installed: pip install mem0ai")
        if not rep["openai_api_key_set"] and not ns.mem0_config:
            raise SystemExit("Set OPENAI_API_KEY or pass --mem0-config.")
        cfg = json.loads(Path(ns.mem0_config).read_text("utf-8")) if ns.mem0_config else None
        backend = Mem0Backend(cfg, ns.llm_model, ns.embedder_model)
        print(f"About to make ~{rep['mem0_add_calls']} Mem0 add() calls "
              f"(each triggers LLM + embedding API calls).")
    else:
        backend = StubBackend()

    report = run(backend, ns.seeds, ns.k, progress=lambda m: print(m, flush=True))
    print(format_table(report))
    if ns.json:
        out = Path(ns.json)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", "utf-8")
        print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
