"""Narrative demo of one user's memory evolving. Run: python run_demo.py"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from fernme.core.graph import UserGraph, AssocGraph, Event, Edge
from fernme.write import Catalog, map_event, observe
from fernme.prior import PopulationPrior
from fernme.retrieve.card import compile_card

cat = Catalog({
    "milk": ["dairy", "organic"], "cheddar": ["dairy", "cheese", "organic"],
    "sourdough": ["bread", "bakery"], "kale": ["produce", "organic"],
    "chips": ["snacks", "size:L"], "soda": ["beverages"],
})

# --- a population prior from a few existing shoppers (organic-leaning store) ---
prior = PopulationPrior("store1")
for u in range(6):
    g = UserGraph("store1", f"seed{u}")
    g.edges["organic"] = Edge(weight=7.0, confidence=0.9, source="known")
    g.edges["dairy"] = Edge(weight=5.0, confidence=0.8, source="known")
    if u == 0:
        g.edges["vegan"] = Edge(weight=8.0, confidence=0.9, source="known")
    prior.update_from_user(g)

print("NEW VISITOR arrives — cold start from population prior (everything 'guessed'):")
ug = UserGraph("store1", "alice")
prior.cold_start(ug)
print("  ", compile_card(ug, AssocGraph("store1"), seeds=[], now=0.0, prior=prior)["wire"])
print("   (? = guessed -> the agent VERIFIES these instead of acting silently)\n")

assoc = AssocGraph("store1")
basket = [["milk", "cheddar", "sourdough"], ["cheddar", "kale"], ["milk", "cheddar"],
          ["sourdough", "kale"], ["cheddar", "milk", "kale"]]
for day, items in enumerate(basket):
    for it in items:
        ev = Event("store1", "alice", float(day), "purchase", {"item_id": it, "qty": 2})
        observe(ug, assoc, ev, map_event(ev, cat))

ug.numeric["dairy_cadence_days"] = 7
print("AFTER 5 shopping trips — card is now mostly 'known' (* = act silently):")
print("  ", compile_card(ug, assoc, seeds=["cheese"], now=5.0, prior=prior)["wire"], "\n")

print("GLASS-BOX EDIT — Alice says 'I'm not buying dairy anymore':")
ug.edges["dairy"] = Edge(weight=0.0, confidence=1.0, source="override", last_reinforced=5.0)
print("  ", compile_card(ug, assoc, seeds=[], now=5.0, prior=prior)["wire"])
print("   (override is locked and never decays)")
