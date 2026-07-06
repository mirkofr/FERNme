"""Synthetic propose-only enrichment eval.

Uses a mock proposal source. No real model is called and no suggestion is
accepted automatically.
"""
from __future__ import annotations

import argparse
import json
import statistics
from dataclasses import replace
from pathlib import Path

from ..config import DEFAULT
from ..service import FernService
from ..store.sqlite_store import SQLiteStore


def _svc(enabled: bool) -> FernService:
    svc = FernService(store=SQLiteStore(":memory:"),
                      cfg=replace(DEFAULT, enrichment_enabled=enabled))
    svc.consent("demo", "alex", True)
    return svc


def _fixture(svc: FernService, seed: int):
    dana = svc.entity_create("demo", "alex", "person", "Dana Reyes")
    felix = svc.entity_create("demo", "alex", "person", "Felix Tan")
    mina = svc.entity_create("demo", "alex", "person", "Mina Park")
    orbit = svc.entity_create("demo", "alex", "project", "Orbit Demo")
    svc.observe("demo", "alex", "note", {
        "text": f"Day {seed}: Dana and Felix are friends. Mina works on Orbit Demo."
    }, ts=float(seed))
    truth = {
        (dana, "friend_of", felix),
        (mina, "works_on", orbit),
    }
    return {"dana": dana, "felix": felix, "mina": mina, "orbit": orbit, "truth": truth}


def _mock_llm(ids):
    def llm_fn(_prompt):
        return json.dumps([
            {"kind": "relation", "subject_id": ids["dana"], "relation": "friend_of",
             "object_id": ids["felix"], "note": "Fictional friend relation"},
            {"kind": "relation", "subject_id": ids["mina"], "relation": "works_on",
             "object_id": ids["orbit"], "note": "Fictional project relation"},
            {"kind": "relation", "subject_id": ids["dana"], "relation": "ignore_previous",
             "object_id": ids["felix"], "note": "bad proposal"},
        ])
    return llm_fn


def _score(svc: FernService, truth):
    rows = svc.store.list_suggestions("demo", "alex", status="pending")
    predicted = {
        (r["payload"].get("subject_id"), r["payload"].get("relation"), r["payload"].get("object_id"))
        for r in rows if r["kind"] == "relation"
    }
    correct = len(predicted & truth)
    precision = correct / len(predicted) if predicted else 0.0
    recall = correct / len(truth) if truth else 0.0
    return precision, recall, len(predicted)


def run(seeds=range(6)):
    rows = []
    for seed in seeds:
        off = _svc(False)
        ids_off = _fixture(off, seed)
        off_report = off.enrich("demo", "alex", llm_fn=_mock_llm(ids_off), now=float(seed))
        off_precision, off_recall, off_suggestions = _score(off, ids_off["truth"])

        on = _svc(True)
        ids_on = _fixture(on, seed)
        on_report = on.enrich("demo", "alex", llm_fn=_mock_llm(ids_on), now=float(seed))
        on_precision, on_recall, on_suggestions = _score(on, ids_on["truth"])

        rows.append({
            "seed": seed,
            "off_precision": off_precision,
            "off_recall": off_recall,
            "off_suggestions": off_suggestions,
            "off_llm_calls": off_report["llm_calls"],
            "on_precision": on_precision,
            "on_recall": on_recall,
            "on_suggestions": on_suggestions,
            "on_llm_calls": on_report["llm_calls"],
            "on_dropped": on_report["dropped"],
        })
    return rows


def _mean_sd(rows, key):
    vals = [float(r[key]) for r in rows]
    return {
        "mean": statistics.mean(vals),
        "sd": statistics.pstdev(vals) if len(vals) > 1 else 0.0,
    }


def summarize(rows):
    keys = [
        "off_precision", "off_recall", "off_suggestions", "off_llm_calls",
        "on_precision", "on_recall", "on_suggestions", "on_llm_calls", "on_dropped",
    ]
    out = {key: _mean_sd(rows, key) for key in keys}
    out["recall_delta"] = {
        "mean": out["on_recall"]["mean"] - out["off_recall"]["mean"],
        "sd": 0.0,
    }
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=6)
    ap.add_argument("--json", default="reports/enrichment.json")
    args = ap.parse_args(argv)
    rows = run(range(args.seeds))
    summary = summarize(rows)
    report = {
        "mode": "synthetic-propose-only-enrichment-eval",
        "seeds": list(range(args.seeds)),
        "rows": rows,
        "summary": summary,
    }
    path = Path(args.json)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")

    print("=" * 72)
    print("SYNTHETIC PROPOSE-ONLY ENRICHMENT EVAL -- mock proposal source")
    print(f"seeds={args.seeds}")
    print("=" * 72)
    print("metric          off mean +/- sd   on mean +/- sd")
    print("--------------- ----------------- ----------------")
    for metric in ("precision", "recall", "suggestions", "llm_calls"):
        off = summary[f"off_{metric}"]
        on = summary[f"on_{metric}"]
        print(f"{metric:<15} {off['mean']:.3f} +/- {off['sd']:.3f}   "
              f"{on['mean']:.3f} +/- {on['sd']:.3f}")
    print(f"recall_delta    {summary['recall_delta']['mean']:.3f}")
    print(f"JSON report written to {path}")


if __name__ == "__main__":
    main()
