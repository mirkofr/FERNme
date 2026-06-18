"""LIVE MEMORY TEST - WRITE SIDE.
Takes Mirko's answers, tags them into FERN events (I act as the event->attribute
mapper), reinforces them as repeated shopping sessions, and PERSISTS to disk.
Run: python live_memory_test.py"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from fernme.core.graph import UserGraph, AssocGraph, Event
from fernme.write import Catalog, map_event, observe
from fernme.store import save_state

STATE = os.path.join(os.path.dirname(__file__), "mirko_state.json")

# --- Mirko's stated profile (from the Q&A) ---
# groceries: Organic | budget: Mid-range | diet: None | restock: Weekly
answer_tags = ["organic", "mid_range"]   # diet 'None' -> deliberately store NOTHING dietary

ug = UserGraph("demo_grocery", "mirko")
assoc = AssocGraph("demo_grocery")

# model a consistent stated preference as a few reinforcing weekly sessions
for week in range(5):
    ev = Event("demo_grocery", "mirko", float(week * 7), "purchase",
               {"tags": answer_tags, "qty": 2})
    observe(ug, assoc, ev, map_event(ev, Catalog()))

# weekly restock -> a numeric side-field (a graph edge can't hold "every 7 days")
ug.numeric["restock_cadence_days"] = 7

save_state(STATE, ug, assoc)
print(f"WROTE {os.path.getsize(STATE)} bytes -> {os.path.basename(STATE)}")
print("stored attributes:", {a: round(e.weight, 1) for a, e in ug.edges.items()})
print("stored numeric:", ug.numeric)
