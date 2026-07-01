"""Synthetic volatility eval with contradiction-scoped verify.

Run: python -m fernme.eval.volatility
"""
from __future__ import annotations

import random
import statistics
from dataclasses import replace

from .. import curation as _curation
from ..confidence import compute
from ..config import DEFAULT
from ..core.graph import AssocGraph, Edge, UserGraph
from ..resolution import needs_verify
from ..retrieve.card import compile_card
from ..write.hebbian import decay

NOW = 1000.0

STILL_TRUE = {
    "permanent": ("name:elena", "allergy:peanut", "origin:seoul"),
    "slow": ("role:founder", "company:newco"),
    "preference": ("pref:concise", "likes:coffee"),
    "habit": ("habit:morning-writing", "tool:codex"),
    "volatile": ("context:fundraising",),
}

SILENT_STALE = {
    "slow": ("city:busan",),
    "preference": ("pref:long-emails", "likes:energy-drinks"),
    "habit": ("habit:night-coding", "tool:old-editor"),
    "volatile": ("context:traveling",),
}

CONTRADICTED_STALE_CANDIDATES = (
    ("employer:oldco", "employer:newco", "slow"),
    ("diet:vegetarian", "diet:pescatarian", "preference"),
    ("status:student", "status:founder", "slow"),
)


def _edge(rng: random.Random, age: float, provenance: str,
          lo: float = 4.0, hi: float = 8.5) -> Edge:
    return Edge(
        weight=rng.uniform(lo, hi),
        confidence=rng.uniform(0.82, 0.98),
        source="known",
        last_reinforced=NOW - age,
        hits=rng.randint(3, 9),
        provenance=provenance,
    )


def _age(rng: random.Random, species: str, stale: bool) -> float:
    if species == "permanent":
        return rng.uniform(80.0, 1600.0)
    if species == "slow":
        return rng.uniform(120.0, 760.0) if stale else rng.uniform(40.0, 680.0)
    if species == "preference":
        return rng.uniform(70.0, 460.0) if stale else rng.uniform(20.0, 340.0)
    if species == "habit":
        return rng.uniform(50.0, 340.0) if stale else rng.uniform(10.0, 250.0)
    if species == "volatile":
        return rng.uniform(18.0, 70.0) if stale else rng.uniform(1.0, 12.0)
    return rng.uniform(10.0, 200.0)


def _profile(seed: int, user: int):
    rng = random.Random(seed * 1009 + user)
    ug = UserGraph("s", f"u{user}")
    still_true, silent_stale, contradicted_stale, stable_truth = set(), set(), set(), set()
    conflict_pairs = {}

    for species, attrs in STILL_TRUE.items():
        for attr in attrs:
            provenance = "stated" if rng.random() < 0.65 else "inferred"
            ug.edges[attr] = _edge(rng, _age(rng, species, stale=False), provenance)
            still_true.add(attr)
            if species in {"permanent", "preference"}:
                stable_truth.add(attr)

    for species, attrs in SILENT_STALE.items():
        for attr in attrs:
            provenance = "stated" if rng.random() < 0.45 else "inferred"
            ug.edges[attr] = _edge(rng, _age(rng, species, stale=True), provenance)
            silent_stale.add(attr)

    # Add 0-2 genuine contradictions per user, counted once per single-value slot.
    n_conflicts = rng.choice((0, 1, 1, 2))
    for old_attr, new_attr, species in rng.sample(list(CONTRADICTED_STALE_CANDIDATES),
                                                  k=n_conflicts):
        old_prov = "stated" if rng.random() < 0.45 else "inferred"
        ug.edges[old_attr] = _edge(rng, _age(rng, species, stale=True), old_prov)
        ug.edges[new_attr] = _edge(rng, rng.uniform(1.0, 35.0), "stated", 5.5, 9.0)
        contradicted_stale.add(old_attr)
        still_true.add(new_attr)
        conflict_pairs[old_attr] = new_attr

    for idx in range(3):
        attr = f"topic:noise-{user}-{idx}"
        ug.edges[attr] = _edge(rng, rng.uniform(5.0, 250.0), "inferred")
    return ug, still_true, silent_stale, contradicted_stale, stable_truth, conflict_pairs


def _clone(ug: UserGraph) -> UserGraph:
    return UserGraph(ug.site, ug.user,
                     {a: Edge(**e.__dict__) for a, e in ug.edges.items()})


def _apply_decay(ug: UserGraph, cfg) -> UserGraph:
    out = _clone(ug)
    decay(out, now=NOW, cfg=cfg)
    return out


def _stable_recall(ug: UserGraph, cfg, stable_truth: set[str]) -> float:
    decayed = _apply_decay(ug, cfg)
    card = compile_card(decayed, AssocGraph("s"), ["who am I?", "what do I like?"],
                        now=NOW, cfg=cfg)
    top = {link["attr"] for link in card["links"][:5]}
    return len(top & stable_truth) / min(5.0, len(stable_truth))


def _stale_high_conf_wrong(ug: UserGraph, cfg, stale: set[str]) -> float:
    if not stale:
        return 0.0
    wrong = 0
    for attr in stale:
        edge = ug.edges[attr]
        conf = compute(edge, NOW, cfg, attr=attr)
        wrong += int(conf >= cfg.conf_high)
    return wrong / float(len(stale))


def _conflict_for(ug: UserGraph, attr: str, conflict_pairs: dict[str, str], cfg) -> float:
    other = conflict_pairs.get(attr)
    if other is None:
        return 0.0
    edge = ug.edges.get(attr)
    other_edge = ug.edges.get(other)
    if edge is None or other_edge is None:
        return 0.0
    return _curation.conflict_score(attr, edge, other, other_edge, cfg.w_max)


def _flagged(ug: UserGraph, cfg, conflict_pairs: dict[str, str],
             use_conflict: bool) -> set[str]:
    if not getattr(cfg, "volatility_confidence", False):
        return set()
    out = set()
    for attr, edge in ug.edges.items():
        conflict = _conflict_for(ug, attr, conflict_pairs, cfg) if use_conflict else 0.0
        if needs_verify(attr, edge, NOW, cfg, conflict=conflict)["verify"]:
            out.add(attr)
    return out


def _metric_counts(flagged: set[str], positives: set[str], negatives: set[str]):
    return {
        "tp": len(flagged & positives),
        "flagged": len(flagged),
        "positives": len(positives),
        "fp": len(flagged & negatives),
        "negatives": len(negatives),
    }


def _rates(counts: dict[str, int]):
    precision = counts["tp"] / float(counts["flagged"]) if counts["flagged"] else 0.0
    recall = counts["tp"] / float(counts["positives"]) if counts["positives"] else 0.0
    nag = counts["fp"] / float(counts["negatives"]) if counts["negatives"] else 0.0
    return precision, recall, nag


def _volatile_weight(ug: UserGraph, cfg, stale: set[str]) -> float:
    decayed = _apply_decay(ug, cfg)
    vals = [
        decayed.edges[attr].weight if attr in decayed.edges else 0.0
        for attr in stale
        if attr.startswith(("project:", "context:"))
    ]
    return statistics.mean(vals) if vals else 0.0


def _summarize(rows: dict[str, list[float]]) -> dict[str, tuple[float, float]]:
    return {k: (statistics.mean(v), statistics.pstdev(v)) for k, v in rows.items()}


def run(seeds: int = 8, users: int = 40,
        verify_age_halflives: float = 1.5,
        verify_age_halflives_stated: float = 3.0,
        verify_age_enabled: bool = False):
    control = replace(DEFAULT, resolution=False, volatility_confidence=False)
    treatment = replace(
        DEFAULT,
        resolution=True,
        volatility_confidence=True,
        verify_age_enabled=verify_age_enabled,
        verify_age_halflives=verify_age_halflives,
        verify_age_halflives_stated=verify_age_halflives_stated,
    )
    rows = {
        "stable_p5_control": [],
        "stable_p5_treatment": [],
        "stale_high_conf_wrong_control": [],
        "stale_high_conf_wrong_treatment": [],
        "volatile_weight_control": [],
        "volatile_weight_treatment": [],
        "verify_precision_overall": [],
        "verify_recall_overall": [],
        "nag_rate_overall": [],
        "verify_precision_contradicted": [],
        "verify_recall_contradicted": [],
        "nag_rate_contradicted": [],
        "verify_precision_silent": [],
        "verify_recall_silent": [],
        "nag_rate_silent": [],
        "age_only_precision_overall": [],
        "age_only_recall_overall": [],
        "age_only_nag_overall": [],
        "conflict_pairs_per_user": [],
    }
    for seed in range(seeds):
        per = {k: [] for k in rows}
        counts = {
            "overall": {"tp": 0, "flagged": 0, "positives": 0, "fp": 0, "negatives": 0},
            "contradicted": {"tp": 0, "flagged": 0, "positives": 0, "fp": 0, "negatives": 0},
            "silent": {"tp": 0, "flagged": 0, "positives": 0, "fp": 0, "negatives": 0},
            "age": {"tp": 0, "flagged": 0, "positives": 0, "fp": 0, "negatives": 0},
        }
        for user in range(users):
            ug, still_true, silent_stale, contradicted_stale, stable_truth, conflict_pairs = (
                _profile(seed, user))
            all_stale = silent_stale | contradicted_stale
            per["stable_p5_control"].append(_stable_recall(ug, control, stable_truth))
            per["stable_p5_treatment"].append(_stable_recall(ug, treatment, stable_truth))
            per["stale_high_conf_wrong_control"].append(
                _stale_high_conf_wrong(ug, control, all_stale))
            per["stale_high_conf_wrong_treatment"].append(
                _stale_high_conf_wrong(ug, treatment, all_stale))
            per["volatile_weight_control"].append(_volatile_weight(ug, control, all_stale))
            per["volatile_weight_treatment"].append(_volatile_weight(ug, treatment, all_stale))

            flagged = _flagged(ug, treatment, conflict_pairs, use_conflict=True)
            for key, positives in (
                ("overall", all_stale),
                ("contradicted", contradicted_stale),
                ("silent", silent_stale),
            ):
                c = _metric_counts(flagged, positives, still_true)
                for name, value in c.items():
                    counts[key][name] += value

            age_cfg = replace(treatment, verify_age_enabled=True)
            age_flagged = _flagged(ug, age_cfg, {}, use_conflict=False)
            c = _metric_counts(age_flagged, all_stale, still_true)
            for name, value in c.items():
                counts["age"][name] += value
            per["conflict_pairs_per_user"].append(float(len(conflict_pairs)))
        for prefix, key in (
            ("verify", "overall"),
            ("verify", "contradicted"),
            ("verify", "silent"),
            ("age_only", "age"),
        ):
            p, r, n = _rates(counts[key])
            if prefix == "verify":
                suffix = key
                per[f"verify_precision_{suffix}"].append(p)
                per[f"verify_recall_{suffix}"].append(r)
                per[f"nag_rate_{suffix}"].append(n)
            else:
                per["age_only_precision_overall"].append(p)
                per["age_only_recall_overall"].append(r)
                per["age_only_nag_overall"].append(n)
        for key in rows:
            rows[key].append(statistics.mean(per[key]))
    return _summarize(rows)


def sweep_thresholds(seeds: int = 5, users: int = 30):
    out = []
    for inferred in (1.0, 1.5, 2.0, 2.5):
        for stated in (2.0, 3.0, 4.0):
            if stated < inferred:
                continue
            result = run(seeds, users, inferred, stated, verify_age_enabled=True)
            out.append({
                "inferred": inferred,
                "stated": stated,
                "recall": result["age_only_recall_overall"][0],
                "precision": result["age_only_precision_overall"][0],
                "nag": result["age_only_nag_overall"][0],
            })
    return out


def _print_metric(name: str, result):
    mean, sd = result[name]
    print(f"  {name:<36} {mean:.3f} +/- {sd:.3f}")


def _f1(precision: float, recall: float) -> float:
    return 0.0 if precision + recall <= 0 else 2.0 * precision * recall / (precision + recall)


def best_operating_point(rows: list[dict]) -> tuple[dict, str]:
    usable = [
        row for row in rows
        if row["precision"] >= 0.60 and row["recall"] >= 0.50 and row["nag"] <= 0.15
    ]
    pool = usable or rows
    best = max(pool, key=lambda r: (_f1(r["precision"], r["recall"]) - r["nag"], r["precision"]))
    if usable:
        note = "usable under provisional synthetic criteria"
    else:
        note = "not yet usable: no age-only point reaches precision>=0.60, recall>=0.50, nag<=0.15"
    return best, note


def main():
    result = run()
    print("=" * 76)
    print("SYNTHETIC VOLATILITY EVAL -- contradiction-scoped verify")
    print("(8 seeds x 40 users; default floor=1.0; volatility decay on in treatment)")
    print("=" * 76)
    for key in (
        "stable_p5_control",
        "stable_p5_treatment",
        "stale_high_conf_wrong_control",
        "stale_high_conf_wrong_treatment",
        "volatile_weight_control",
        "volatile_weight_treatment",
        "verify_precision_overall",
        "verify_recall_overall",
        "nag_rate_overall",
        "verify_precision_contradicted",
        "verify_recall_contradicted",
        "nag_rate_contradicted",
        "verify_precision_silent",
        "verify_recall_silent",
        "nag_rate_silent",
        "age_only_precision_overall",
        "age_only_recall_overall",
        "age_only_nag_overall",
        "conflict_pairs_per_user",
    ):
        _print_metric(key, result)
    print("-" * 76)
    print("Age-only threshold sweep, treatment only: recall vs precision vs nag rate")
    print(f"  {'inferred':>8} {'stated':>8} {'recall':>8} {'precision':>10} {'nag':>8}")
    rows = sweep_thresholds()
    for row in rows:
        print(f"  {row['inferred']:>8.1f} {row['stated']:>8.1f} "
              f"{row['recall']:>8.3f} {row['precision']:>10.3f} {row['nag']:>8.3f}")
    best, note = best_operating_point(rows)
    print("-" * 76)
    print("Best age-only operating point by F1-minus-nag:")
    print(f"  inferred={best['inferred']:.1f} stated={best['stated']:.1f} "
          f"recall={best['recall']:.3f} precision={best['precision']:.3f} "
          f"nag={best['nag']:.3f}")
    print(f"Usability note: {note}.")
    return result


if __name__ == "__main__":
    main()
