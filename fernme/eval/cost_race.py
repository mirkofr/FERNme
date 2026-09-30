"""Side-by-side token race: FERNme card vs full history vs Mem0's own prompts.

    python -m fernme.eval.cost_race --turns 300 --json reports/cost_race.json
    python -m fernme.eval.cost_race --turns 300 --with-mem0-prompts --json ...

One fictional user produces one short message per turn (synthetic stream with
a taste drift at the midpoint). At every turn the script records:

- ``fern``: tokens of the real FERNme card the agent would inject, and FERNme's
  LLM calls (always 0 on the write path).
- ``history``: tokens of the whole message history, i.e. the "paste every note
  into the prompt" approach (a growing CLAUDE.md / transcript).
- ``mem0`` (optional, needs ``pip install mem0ai``; no API key, no network):
  the real Mem0 OSS pipeline runs with a deterministic stand-in model. Input
  tokens are counted from the exact prompts Mem0 builds for its extraction
  call on every ``add()``, and read tokens from the memories its ``search()``
  returns. The stand-in decides memory *content*, so these are measurements of
  Mem0's prompt sizes on this stream, not of a real model's behavior. Output
  tokens are approximated by the stand-in's JSON reply size.

Everything is synthetic; nothing here describes real users.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import re
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from ..retrieve.card import estimate_tokens
from ..service import FernService

SITE = "race.example"
USER = "fictional-racer"

_BEFORE = ("pref:oat-milk", "pref:dark-roast", "food:croissant", "style:concise",
           "topic:python", "topic:gardening", "pace:slow-browse", "brand:maple-home")
_AFTER = ("pref:oat-milk", "pref:mint-tea", "food:rice-bowl", "style:concise",
          "topic:rust", "topic:gardening", "pace:quick-pickup", "brand:river-studio")
_NOISE = ("topic:weather", "topic:parking", "food:cookie", "topic:receipt",
          "topic:holiday", "pref:window-seat", "topic:music", "topic:news")
_TEMPLATES = (
    "Can you help me again? Keep it {style}. I had {food} with {drink} today.",
    "Quick one about {topic}. By the way I'm into {topic2} lately and I shop at {brand}.",
    "Remind me: I usually go {pace}. Also {noise} came up this morning.",
    "Thanks. Coffee order is {drink}; lunch was {food}. Still working on {topic}.",
)


def _h(tag: str) -> str:
    return tag.split(":", 1)[1].replace("-", " ")


def synthetic_stream(turns: int, seed: int = 0) -> List[Dict]:
    """Deterministic fictional message stream with a drift at turns // 2."""
    rng = random.Random(seed)
    out = []
    for t in range(turns):
        core = _BEFORE if t < turns // 2 else _AFTER
        pick = {
            "style": core[3], "food": core[2], "drink": core[rng.choice((0, 1))],
            "topic": core[4], "topic2": core[5], "brand": core[7], "pace": core[6],
            "noise": rng.choice(_NOISE),
        }
        tpl = _TEMPLATES[t % len(_TEMPLATES)]
        text = tpl.format(**{k: _h(v) for k, v in pick.items()})
        fields = re.findall(r"{(\w+)}", tpl)
        tags = list(dict.fromkeys(pick[f] for f in fields))
        out.append({"turn": t + 1, "text": text, "tags": tags})
    return out


def _fern_series(stream: Sequence[Dict]) -> Dict[str, List[int]]:
    svc = FernService(db_path=":memory:")
    svc.consent(SITE, USER, True)
    card_tokens, calls = [], []
    for msg in stream:
        svc.observe(SITE, USER, "chat", {"tags": msg["tags"], "text": msg["text"]},
                    ts=float(msg["turn"]))
        card = svc.card(SITE, USER, now=float(msg["turn"]) + 0.5)
        card_tokens.append(int(card["tokens"]))
        calls.append(int(svc.llm_calls))
    final = svc.card(SITE, USER, now=float(len(stream)) + 0.5)
    return {"read_tokens": card_tokens, "llm_calls_cum": calls,
            "final_card": final["wire"]}


def _history_series(stream: Sequence[Dict]) -> Dict[str, List[int]]:
    running, series = 0, []
    for msg in stream:
        running += estimate_tokens(msg["text"] + "\n")
        series.append(running)
    return {"read_tokens": series, "llm_calls_cum": [0] * len(stream)}


def _vec(text: str, dims: int = 1536) -> List[float]:
    v = [0.0] * dims
    for w in re.findall(r"[a-z]+", text.lower()):
        v[int(hashlib.md5(w.encode()).hexdigest(), 16) % dims] += 1.0
    n = sum(x * x for x in v) ** 0.5
    return [x / n for x in v] if n else v


def _mem0_series(stream: Sequence[Dict], k: int = 10) -> Optional[Dict]:
    """Run real Mem0 OSS with a stand-in model; count its prompt tokens."""
    try:
        os.environ.setdefault("MEM0_TELEMETRY", "False")
        os.environ.setdefault("OPENAI_API_KEY", "not-used-stand-in-model")
        from mem0 import Memory
    except Exception:
        return None
    write_in, write_out, read_tokens, calls = [], [], [], []
    state = {"in": 0, "out": 0, "calls": 0}

    def stand_in(messages, **_kw):
        state["calls"] += 1
        state["in"] += sum(estimate_tokens(str(m.get("content", ""))) for m in messages)
        user = str(messages[-1].get("content", ""))
        latest = re.findall(r"Can you[^\n]*|Quick one[^\n]*|Remind me[^\n]*|Thanks\.[^\n]*", user)
        facts = [s.strip()[:160] for s in latest[-1:]] or ["User sent a message."]
        reply = json.dumps({"memory": [{"text": f} for f in facts]})
        state["out"] += estimate_tokens(reply)
        return reply

    with tempfile.TemporaryDirectory(prefix="fernme_cost_race_") as d:
        m = Memory.from_config({
            "llm": {"provider": "openai", "config": {"model": "stand-in"}},
            "embedder": {"provider": "openai", "config": {"model": "stand-in"}},
            "vector_store": {"provider": "qdrant", "config": {
                "path": os.path.join(d, "qdrant"), "collection_name": "race"}},
            "history_db_path": os.path.join(d, "history.db"),
        })
        m.llm.generate_response = stand_in
        m.embedding_model.embed = lambda t, *a, **kw: _vec(t)
        m.embedding_model.embed_batch = lambda ts, *a, **kw: [_vec(t) for t in ts]
        for msg in stream:
            before_in, before_out = state["in"], state["out"]
            m.add([{"role": "user", "content": msg["text"]}], user_id=USER)
            write_in.append(state["in"] - before_in)
            write_out.append(state["out"] - before_out)
            res = m.search("What should I know about this user right now?", top_k=k,
                           filters={"user_id": USER}, threshold=0.0)
            mems = [r.get("memory", "") for r in res.get("results", [])]
            read_tokens.append(estimate_tokens(" ".join(mems)) if mems else 0)
            calls.append(state["calls"])
    return {"read_tokens": read_tokens, "write_in_tokens": write_in,
            "write_out_tokens": write_out, "llm_calls_cum": calls, "search_top_k": k}


def run(turns: int = 300, seed: int = 0, with_mem0: bool = False) -> Dict:
    stream = synthetic_stream(turns, seed)
    report = {
        "mode": "synthetic-cost-race", "schema_version": 1, "turns": turns, "seed": seed,
        "sample_messages": [m["text"] for m in stream[:3]],
        "fern": _fern_series(stream),
        "history": _history_series(stream),
        "mem0": None,
        "notes": [
            "Synthetic fictional user; one message per turn; taste drift at turns/2.",
            "fern.read_tokens = real FERNme card tokens injected per turn.",
            "history.read_tokens = the whole message history injected per turn.",
        ],
    }
    if with_mem0:
        report["mem0"] = _mem0_series(stream)
        if report["mem0"] is None:
            report["notes"].append("mem0 series skipped: mem0ai not installed.")
        else:
            import importlib.metadata as md
            report["mem0_version"] = md.version("mem0ai")
            report["notes"].append(
                "mem0 = real Mem0 OSS pipeline with a deterministic stand-in model; "
                "write_in_tokens are counted from Mem0's own extraction prompts; "
                "write_out_tokens approximate the reply size; memory content is the "
                "stand-in's, not a real model's.")
    return report


def summary(report: Dict) -> str:
    t = report["turns"]
    f, h, m = report["fern"], report["history"], report.get("mem0")
    lines = [f"SYNTHETIC cost race, {t} turns",
             f"  FERNme card tokens: first {f['read_tokens'][0]}, last {f['read_tokens'][-1]}, "
             f"max {max(f['read_tokens'])}; LLM calls {f['llm_calls_cum'][-1]}",
             f"  full history tokens: last {h['read_tokens'][-1]}"]
    if m:
        lines.append(f"  Mem0 (stand-in model): read tokens last {m['read_tokens'][-1]}; "
                     f"write prompt tokens total {sum(m['write_in_tokens'])}; "
                     f"LLM calls {m['llm_calls_cum'][-1]}")
    return "\n".join(lines)


TEMPLATE = Path(__file__).resolve().parents[2] / "demo" / "token_race.template.html"


def write_html(report: Dict, path: str) -> Path:
    """Fill the demo template with this run's series. Requires the mem0 series."""
    m = report.get("mem0")
    if not m:
        raise SystemExit("--html needs --with-mem0-prompts (and mem0ai installed).")
    data = {"turns": report["turns"], "fern": report["fern"]["read_tokens"],
            "hist": report["history"]["read_tokens"], "m_in": m["write_in_tokens"],
            "m_out": m["write_out_tokens"], "m_read": m["read_tokens"],
            "mem0v": report.get("mem0_version", ""), "samples": report["sample_messages"]}
    page = TEMPLATE.read_text("utf-8").replace("__DATA__", json.dumps(data, separators=(",", ":")))
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page, "utf-8")
    return out


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Synthetic side-by-side token race.")
    ap.add_argument("--turns", type=int, default=300)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--with-mem0-prompts", action="store_true",
                    help="also run Mem0 OSS with a stand-in model (needs mem0ai; no API)")
    ap.add_argument("--json")
    ap.add_argument("--html", help="write the side-by-side demo page (repo checkout only)")
    ns = ap.parse_args(argv)
    rep = run(ns.turns, ns.seed, ns.with_mem0_prompts)
    print(summary(rep))
    if ns.json:
        out = Path(ns.json)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(rep, indent=1) + "\n", "utf-8")
        print(f"wrote {out}")
    if ns.html:
        print(f"wrote {write_html(rep, ns.html)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
