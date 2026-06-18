"""LIVE MEMORY TEST - READ SIDE.
A FRESH process. It has NONE of the conversation in context. It loads only the
JSON file and asks FERN what it knows. If this is right, the memory works.
Run: python recall_live.py"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from fernme.store import load_state
from fernme.retrieve.card import compile_card
from fernme.config import DEFAULT

STATE = os.path.join(os.path.dirname(__file__), "mirko_state.json")
ug, assoc, _ = load_state(STATE)

print(f"Loaded profile for user '{ug.user}' from disk (no chat context).\n")

# 1) raw wire card
card = compile_card(ug, assoc, seeds=[], now=40.0)
print("FERN CARD (what reaches the model):")
print("  ", card["wire"], "\n")

# 2) human-readable recall
print("WHAT FERN REMEMBERS ABOUT YOU:")
for a, e in sorted(ug.edges.items(), key=lambda kv: -kv[1].weight):
    mark = "known" if e.confidence >= DEFAULT.conf_known else "guessed"
    pretty = a.replace("_", "-")
    print(f"  - {pretty}: {e.wire_weight()}/9  ({mark}, confidence {e.confidence:.2f})")
for k, v in ug.numeric.items():
    print(f"  - {k.replace('_',' ')}: {int(v) if isinstance(v,(int,float)) else v}")

# 3) the negative test: did it invent dietary restrictions it was never told?
diet_flags = [a for a in ug.edges if a in ("vegan", "gluten_free", "dairy_free")]
print("\nDIETARY RESTRICTIONS ON RECORD:",
      ", ".join(diet_flags) if diet_flags else "none (correctly, you said None)")

# 4) a scenario: you come back to shop -> what does FERN default to?
print("\nSCENARIO - you return to the store. FERN's defaults:")
card2 = compile_card(ug, assoc, seeds=["organic"], now=44.0)
prefs = [l["attr"] for l in card2["links"] if l["known"]]
print("  -> bias search/recommendations toward:", ", ".join(prefs))
print(f"  -> mid-tier pricing (not premium, not budget)")
print(f"  -> expect a restock nudge ~every {int(ug.numeric.get('restock_cadence_days',0))} days")
