"""COST / QUALITY PARETO — where does each memory strategy sit on quality vs. $?

What is MEASURED (real code, this repo):
  * FERN's recall on simple preferences (run on the simulator).
  * FERN's per-turn card tokens, and the full-history token growth.
What is MODELED (explicit, tunable assumptions — no real LLM is called here):
  * how much 'nuanced/causal' preference each strategy recovers (NUANCE table),
  * the token sizes and price of LLM memory ops (PRICES / TOKENS).

So this shows the STRUCTURE of the cost/quality trade-off under stated assumptions
-- not a measured real-world number. All assumptions are at the top; change them
and the table updates. Run: python -m fern.eval.pareto
"""
from __future__ import annotations
import statistics
from dataclasses import dataclass
from .quality import run as quality_run
from .experiment import run as cost_run

# ---- ASSUMPTIONS (edit freely) ----------------------------------------------
PRICE_IN = 0.30 / 1e6     # $/token, small model input  (~Haiku-class)
PRICE_OUT = 1.20 / 1e6    # $/token, small model output
# Everyone is assumed to use the SAME cheap model -> FERN's win is call VOLUME,
# not model choice (a deliberately conservative comparison).

W_SIMPLE, W_NUANCE = 0.70, 0.30           # share of preferences that are simple vs nuanced
LLM_SIMPLE = 0.80                          # an LLM also nails simple prefs (ceiling)

# nuance recovered by each strategy (mechanism-based assumption, 0..1)
NUANCE = {
    "no-memory": 0.0, "FERN-pure": 0.0, "full-history@120": 0.85,
    "Mem0-style": 0.85, "FERN+gated": 0.45, "FERN+offline": 0.70,
}
GATE_RATE = 0.10           # fraction of turns FERN+gated invokes the small LLM
# full-history token cost GROWS with conversation length; we use the MEASURED
# value at a 120-interaction horizon and note it keeps growing (FERN/Mem0 stay flat).
MEM0_RETRIEVE = 1000       # tokens of facts Mem0 injects per turn (read)
MEM0_WRITE_IN, MEM0_WRITE_OUT = 600, 120   # per extract+reconcile, x2 calls/turn
GATED_IN, GATED_OUT = 300, 50              # one small tagging call
OFFLINE_IN, OFFLINE_OUT = 200, 30          # per-event nightly consolidation (amortized)


@dataclass
class Strat:
    name: str
    read_tokens: float      # extra tokens added to the agent context per turn
    write_in: float         # LLM input tokens spent per turn (memory's own calls)
    write_out: float        # LLM output tokens per turn

    def cost_per_1k(self) -> float:
        per_turn = (self.read_tokens + self.write_in) * PRICE_IN + self.write_out * PRICE_OUT
        return per_turn * 1000


def quality(name: str, fern_simple: float) -> float:
    simple = 0.0 if name == "no-memory" else (fern_simple if name.startswith("FERN") else LLM_SIMPLE)
    return W_SIMPLE * simple + W_NUANCE * NUANCE[name]


def main():
    # --- measured pieces ---
    q = quality_run(seeds=4)
    fern_simple = q["FERN"][0]
    c = cost_run(seed=0)
    card_tokens = statistics.mean(c["fern"])              # ~25, flat
    print("measured: FERN simple-recall = %.3f | card = %.1f tok | full-history@120 = %.0f tok"
          % (fern_simple, card_tokens, c["hist"][-1]))

    strategies = [
        Strat("no-memory", 0, 0, 0),
        Strat("FERN-pure", card_tokens, 0, 0),
        Strat("FERN+gated", card_tokens, GATE_RATE * GATED_IN, GATE_RATE * GATED_OUT),
        Strat("FERN+offline", card_tokens, OFFLINE_IN, OFFLINE_OUT),   # 1 event/turn amortized
        Strat("Mem0-style", MEM0_RETRIEVE, 2 * MEM0_WRITE_IN, 2 * MEM0_WRITE_OUT),
        Strat("full-history@120", c["hist"][-1], 0, 0),
    ]

    rows = []
    for s in strategies:
        rows.append((s.name, quality(s.name, fern_simple), s.cost_per_1k()))
    rows.sort(key=lambda r: r[2])

    print("\n" + "=" * 64)
    print("COST / QUALITY  (cost = $ per 1,000 interactions, assumed prices)")
    print("=" * 64)
    print(f"{'strategy':<14}{'quality':>9}{'$/1k int':>12}{'vs FERN-pure':>14}")
    base = next(c for n, q_, c in rows if n == "FERN-pure")
    for name, qv, cost in rows:
        mult = "—" if base == 0 else (f"{cost/base:.0f}x" if base else "n/a")
        if name == "FERN-pure": mult = "1x"
        if base == 0 and name != "no-memory": mult = "inf"
        print(f"{name:<14}{qv:>9.3f}{cost:>12.4f}{mult:>14}")

    # Pareto frontier (max quality at <= cost)
    print("-" * 64)
    front, best_q = [], -1
    for name, qv, cost in rows:
        if qv > best_q:
            front.append(name); best_q = qv
    print("Pareto-optimal (cheapest-first):", " -> ".join(front))
    d = {n: (q_, c_) for n, q_, c_ in rows}
    ceil = max(q_ for _, q_, _ in rows)
    print("-" * 64)
    for arm in ("FERN+gated", "FERN+offline"):
        qv, cost = d[arm]
        print(f"{arm}: {100*qv/ceil:.0f}% of the LLM-ceiling quality at "
              f"{d['Mem0-style'][1]/cost:.0f}x lower cost than Mem0-style.")
    print("(full-history cost shown at 120 interactions and KEEPS GROWING; FERN & Mem0 are flat.)")
    print("\nMODELED assumptions (nuance, token sizes, prices) are at the top of this file.")
    _plot(rows)
    return rows


def _plot(rows, out="results_cost_quality_pareto.png"):
    try:
        import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
    except Exception:
        return
    rows = [r for r in rows if r[0] != "no-memory"]
    xs = [c for _, _, c in rows]; ys = [q for _, q, _ in rows]; names = [n for n, _, _ in rows]
    fig, ax = plt.subplots(figsize=(9, 5.5))
    ax.scatter(xs, ys, s=90, color="#2471a3", zorder=3)
    # per-point label placement to avoid overlap (dx_pts, dy_pts, ha, va)
    label = {"full-history@120": "full-history (@120, grows)", "Mem0-style": "Mem0"}
    off = {
        "FERN-pure":        (10, 0, "left", "center"),
        "FERN+gated":       (10, 0, "left", "center"),
        "FERN+offline":     (10, 0, "left", "center"),
        "full-history@120": (0, -16, "center", "top"),     # well BELOW its point
        "Mem0-style":       (0, 16, "center", "bottom"),   # well ABOVE its point
    }
    for n, x, y in zip(names, xs, ys):
        dx, dy, ha, va = off.get(n, (8, 4, "left", "bottom"))
        ax.annotate(label.get(n, n), (x, y), xytext=(dx, dy), textcoords="offset points",
                    fontsize=10, ha=ha, va=va)
    order = sorted(zip(xs, ys)); fx, fy, best = [], [], -1
    for x, y in order:
        if y > best: fx.append(x); fy.append(y); best = y
    ax.plot(fx, fy, "--", color="#1d9e75", lw=1.8, zorder=2, label="Pareto frontier")
    ax.set_xscale("log")
    ax.set_xlim(min(xs) * 0.6, max(xs) * 2.4)        # right margin so labels fit
    ax.set_ylim(min(ys) - 0.04, max(ys) + 0.09)
    ax.set_xlabel("cost  ($ per 1,000 interactions, log scale)")
    ax.set_ylabel("quality (composite recall)")
    ax.set_title("Memory strategies: quality vs. cost\n"
                 "FERN+gated / +offline sit on the efficient knee")
    ax.grid(alpha=0.25, which="both"); ax.legend(loc="lower right", frameon=False)
    fig.tight_layout(); fig.savefig(out, dpi=130); print("wrote", out)
