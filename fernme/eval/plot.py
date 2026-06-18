"""Render the Q1 cost-flatness figure to a PNG. Run: python -m fern.eval.plot"""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from .experiment import run


def main(out="results_cost_flatness.png"):
    r = run()
    xs, fern, hist = r["xs"], r["fern"], r["hist"]
    fig, ax = plt.subplots(figsize=(8, 5))
    ax.plot(xs, hist, label="Full history in context (baseline)", lw=2.2, color="#c0392b")
    ax.plot(xs, fern, label="FERN card (this work)", lw=2.2, color="#2471a3")
    ax.set_xlabel("Interactions (profile size)")
    ax.set_ylabel("Per-turn memory tokens")
    ax.set_title("Per-turn token cost vs. profile size\nFERN stays flat; full history grows linearly")
    ax.legend(loc="upper left", frameon=False)
    ax.grid(alpha=0.25)
    fig.tight_layout()
    fig.savefig(out, dpi=130)
    print("wrote", out)


if __name__ == "__main__":
    main()
