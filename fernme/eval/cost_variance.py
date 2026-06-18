"""Multi-seed variance on the headline cost claim. Run: python -m fern.eval.cost_variance"""
from __future__ import annotations
import statistics
from .experiment import run


def main(seeds=5):
    slopes, ratios, cards = [], [], []
    for s in range(seeds):
        r = run(seed=s)
        xs, fern, hist = r["xs"], r["fern"], r["hist"]
        half = len(xs) // 2
        slopes.append((fern[-1] - fern[half]) / (xs[-1] - xs[half]))
        ratios.append(hist[-1] / max(fern[-1], 1))
        cards.append(statistics.mean(fern))
    def ms(v): return (statistics.mean(v), statistics.pstdev(v))
    sm, ss = ms(slopes); rm, rs = ms(ratios); cm, cs = ms(cards)
    print("=" * 56)
    print(f"COST CLAIM — variance over {seeds} seeds")
    print("=" * 56)
    print(f"  FERN card tokens (mean):     {cm:6.1f} +/- {cs:.1f}")
    print(f"  FERN token slope/interaction:{sm:+.4f} +/- {ss:.4f}  (~0 = flat)")
    print(f"  full-history/FERN at turn 120:{rm:6.1f}x +/- {rs:.1f}")
    print("  write-time LLM calls: 0 (deterministic; no per-seed variance)")


if __name__ == "__main__":
    main()
