"""The Lego demo: one person, three sites, one user-owned supernode.
Privacy model: DEFAULT-DENY cross-site. Run: python supernode_demo.py"""
import sys, os, tempfile
sys.path.insert(0, os.path.dirname(__file__))
from fernme.service import FernService

fd, db = tempfile.mkstemp(suffix=".db"); os.close(fd); os.remove(db)
svc = FernService(db)
P = "person:james"

def use(site, user, sessions, numeric=None):
    svc.consent(site, user, True)
    for ts, tags in enumerate(sessions):
        svc.observe(site, user, "event", {"tags": tags, "qty": 2}, ts=ts)
    for k, v in (numeric or {}).items():
        svc.set_numeric(site, user, k, v)
    svc.link_identity(P, site, user)              # he SIGNS IN with his FERN account

use("freshmart", "u4471",
    [["vegetarian","dairy"],["vegetarian","allergy:almond"],["vegetarian","dairy"],
     ["dairy","allergy:almond"],["vegetarian","dairy"]], numeric={"milk_cadence_days":4})
use("dateme", "james_d",
    [["dating:blonde","profession:doctor"],["dating:blonde"],["profession:doctor","dating:blonde"]])
use("bookmytrip", "jb_travel",
    [["travel:bahamas","hotel:5star"],["flight:firstclass","travel:beach"],["hotel:5star","flight:firstclass"]])

print("="*68)
print("OWNER VIEW — James sees his whole self (he owns the supernode)")
print("="*68)
for l in svc.supernode_card(P)["links"]:
    print(f"  {l['attr']:<22} {l['w']}/9  from {', '.join(l['from'])}" + (" [SENSITIVE]" if l['sensitive'] else ""))

print("\n" + "="*68)
print("DEFAULT-DENY — what each site sees with NO sharing set")
print("="*68)
print("  freshmart  :", svc.view_for_site(P,"freshmart")["wire"])
print("  bookmytrip :", svc.view_for_site(P,"bookmytrip")["wire"])
print("  -> each site sees ONLY its own bricks. No cross-site leakage.")

print("\n" + "="*68)
print("USER OPTS IN — James lets a NEW meal-kit site use his diet + allergy")
print("="*68)
svc.consent("mealkit","jk",True); svc.link_identity(P,"mealkit","jk")
print("  mealkit before sharing:", svc.view_for_site(P,"mealkit")["wire"], "(nothing — brand new)")
svc.set_share(P,"mealkit","vegetarian",True)
svc.set_share(P,"mealkit","allergy",True)
print("  mealkit after James shares diet+allergy:")
print("   ", svc.view_for_site(P,"mealkit")["wire"])
print("  -> it can now avoid almonds for him. Travel/dating stay invisible to it.")

print("\n" + "="*68)
print("POP A BRICK OUT — James unlinks the dating app")
print("="*68)
svc.unlink_identity(P,"dateme","james_d")
rem = [l["attr"] for l in svc.supernode_card(P)["links"] if "dating" in l["attr"] or "profession" in l["attr"]]
print("  dating/profession remaining:", rem or "none — gone from the supernode")
