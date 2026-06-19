"""Salience demo: a one-time, high-salience signal resists forgetting where a
neutral one fades. Standalone (no dataset). Generates 12_salience.png."""
import os, sys, math
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from dataclasses import replace
from fernme.config import DEFAULT
from fernme.core.graph import UserGraph, AssocGraph, Event
from fernme.write.hebbian import observe, decay

OUT = os.environ.get("OUT", os.path.join(os.path.dirname(__file__), "elena", "figures"))
os.makedirs(OUT, exist_ok=True)
cfg = replace(DEFAULT, salience_beta=0.9)          # salience ON for the demo
ug = UserGraph("s","u"); ag = AssocGraph("s")
# both seen once, same starting strength; one is behaviorally significant (intensity 1.0)
observe(ug, ag, Event("s","u",0.0,"v",{}), [("pref:neutral",5.0)], cfg)
observe(ug, ag, Event("s","u",0.0,"v",{}), [("pref:intense",5.0)], cfg, salience={"pref:intense":1.0})

days = list(range(0,141)); n_w=[]; i_w=[]
for t in days:
    n_w.append(ug.edges["pref:neutral"].weight if "pref:neutral" in ug.edges else 0.0)
    i_w.append(ug.edges["pref:intense"].weight if "pref:intense" in ug.edges else 0.0)
    decay(ug, now=float(t+1), cfg=cfg)

plt.rcParams.update({"figure.dpi":130,"font.size":11,"axes.grid":True,"grid.alpha":.25,
                     "axes.spines.top":False,"axes.spines.right":False})
TEAL,GRAY,RED="#0f6e56","#7a7972","#a32d2d"
fig,ax=plt.subplots(figsize=(7,4.2))
ax.plot(days, i_w, color=TEAL, lw=2.6, label="high-salience signal (seen once)")
ax.plot(days, n_w, color=GRAY, lw=2.2, label="neutral signal (seen once)")
ax.axhline(cfg.floor, color=RED, ls="--", lw=1.4, label=f"forget threshold ({cfg.floor})")
ax.fill_between(days, cfg.floor, i_w, where=[a>cfg.floor for a in i_w], color=TEAL, alpha=.08)
ax.set_xlabel("days since the single observation (no reinforcement)")
ax.set_ylabel("edge weight (0-9)")
ax.set_title("Salience: a significant one-time signal resists forgetting")
ax.legend(fontsize=9); fig.tight_layout(); fig.savefig(f"{OUT}/12_salience.png"); plt.close(fig)
print("wrote", f"{OUT}/12_salience.png")
