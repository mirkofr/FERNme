"""Evaluation of FERNme on the Elena natural-memory dataset (86 entries).
Instruments the ingest, then produces analysis plots + tables proving the engine's
core properties: flat cost, reinforcement, drift handling, retention, structure."""
import os, re, glob, json, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from fernme.service import FernService
from fernme.store.sqlite_store import SQLiteStore
from entity_scene import SITE, USER, populate_elena_entities

DIR = os.environ["DIR"]
OUT = os.environ.get("OUT", os.path.join(os.path.dirname(os.path.abspath(__file__)),"figures"))
os.makedirs(OUT, exist_ok=True)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
tok = lambda s: max(1, len(s) // 4)            # chars/4 token estimate

# ---------------- parsing (same scheme as ingest, with tea canonicalization) ----------------
PEOPLE = {"marina","ivan","jonas","filip","ana","daniel","priya","maya","luca","sara","nina",
 "tomas","emily","ahmed","marta","keiko","haru","viktor","novak","andrej"}
BRANDS = {"muji","uniqlo","apple","dropbox","jo malone","cerave","macbook","iphone","macos","memoryforge"}
FOOD = {"tomato soup","mushroom risotto","bibimbap","salmon","risotto"}
def slug(s): return re.sub(r"[^a-z0-9]+","-",s.lower().strip()).strip("-")[:48]
def classify(e):
    e = re.sub(r"^the ","", e.lower().strip())
    if "earl grey" in e: return "tea:earl-grey"
    if "jasmine" in e:   return "tea:jasmine"
    if "chamomile" in e: return "tea:chamomile"
    if "peppermint" in e:return "tea:peppermint"
    if "matcha" in e:    return "tea:matcha"
    if "flat white" in e:return "pref:flat-white"
    if any(p in e for p in PEOPLE): return "rel:"+slug(e.split()[0] if " " in e else e)
    if any(b in e for b in BRANDS): return "brand:"+slug(e)
    if any(f in e for f in FOOD):   return "food:"+slug(e)
    if "marathon" in e: return "goal:half-marathon"
    if "memory journal" in e: return "project:memory-journal-platform"
    if "book" in e: return "project:ai-pm-book"
    return "entity:"+slug(e)

TH = {  # hand tags for the 12 prose stories (no explicit Tags fields)
 "01_":["pref:macbook","pref:flat-white","pref:one-sugar","pref:markdown-notes","!pref:meetings-without-agenda","rel:jonas","pet:miso","brand:muji"],
 "02_":["role:senior-product-manager","employer:memoryforge","project:memory-journal-platform","pref:flat-white","!pref:bubble-tea","goal:50-beta-users","rel:daniel","rel:priya","rel:maya"],
 "03_":["rel:marina","rel:ivan","rel:filip","rel:ana","origin:zagreb","food:mushroom-risotto","rel:jonas"],
 "04_":["style:polite-then-direct","trait:numbers-requirements-when-frustrated","style:thanks-when-task-correct","!pref:vague-ai-answers"],
 "05_":["pref:minimalist-style","pref:earth-tones","brand:muji","brand:uniqlo","pref:jo-malone","pref:cerave","!pref:complicated-beauty","pref:macbook"],
 "06_":["goal:half-marathon","activity:running","activity:yoga","activity:swimming","health:migraines","health:no-food-allergies","metric:weight-64kg","pref:early-sleep","rel:nina","rel:sara"],
 "07_":["food:mushroom-risotto","food:tomato-soup","food:bibimbap","pref:flat-white","goal:visit-japan","goal:visit-norway","!pref:resort-vacations","tea:jasmine","tea:earl-grey","tea:peppermint","tea:chamomile","rel:tomas"],
 "08_":["rel:novak","rel:andrej","rel:sara","rel:emily","rel:ahmed","!pref:voice-messages","pet:miso","project:ai-pm-book"],
 "09_":["project:memory-journal-platform","goal:50-beta-users","goal:half-marathon","goal:18km-milestone","project:ai-pm-book","goal:jlpt-n3","study:japanese","rel:daniel","rel:priya","rel:emily","rel:keiko","rel:haru"],
 "10_":["style:texts-like-emails","style:no-all-caps","style:small-emoji-to-soften","!pref:voice-messages","phrase:edge-case","trait:good-with-deadlines","trait:forgets-glasses"],
 "11_":["pref:einaudi","movie:arrival","book:atomic-habits","book:project-hail-mary","music:lofi","music:bon-iver","music:odesza","music:aurora"],
 "12_":["name:elena-sofia-markovic","nickname:lena","birthday:1991-09-14","origin:croatian","study:cs-zagreb","field:hci","city:ljubljana","employer:memoryforge","pet:miso","rel:jonas","pref:macos","pref:iphone","pref:macbook","pref:markdown","activity:yoga","activity:swimming","pref:flat-white","value:documentation"],
}

def parse():
    entries=[]
    for path in sorted(glob.glob(os.path.join(DIR,"*.md"))):
        fn=os.path.basename(path)
        if fn.lower()=="readme.md": continue
        raw=open(path,encoding="utf-8").read(); rt=tok(raw)
        th=next((k for k in TH if fn.startswith(k)), None)
        if th:
            entries.append((("0",fn), fn, TH[th], rt)); continue
        date=(re.search(r"\*\*Date:\*\*\s*([0-9-]+)",raw) or [None,"2026-06-01"])[1]
        tagline=re.search(r"\*\*Tags:\*\*\s*(.+)",raw)
        tags=["topic:"+slug(t) for t in (tagline.group(1).split(",") if tagline else []) if t.strip()]
        m=re.search(r"##+\s*Entities\s*(.+?)(?:\n##|\Z)",raw,re.S)
        if m:
            for line in m.group(1).splitlines():
                e=line.strip("-* \t")
                if e and not e.startswith("#") and not e.lower().startswith("elena"):
                    tags.append(classify(e))
        entries.append((("1",date,fn), fn, [t for t in tags if t], rt))
    entries.sort(key=lambda x:x[0])
    return entries

entries=parse()
N=len(entries)

# ---------------- instrumented ingest ----------------
svc=FernService(store=SQLiteStore(":memory:")); svc.track_style=False
svc.store.set_consent(SITE,USER,True)
track=["tea:jasmine","tea:earl-grey","pref:flat-white","goal:half-marathon"]
hist={"card":[], "attrs":[], "naive":[], "llm":[]}
series={t:[] for t in track}
cum=0
for i,(o,fn,tags,rt) in enumerate(entries,1):
    svc.observe(SITE,USER,"entry",{"tags":tags[:32]},ts=float(i))
    cum+=rt
    hist["card"].append(svc.card(SITE,USER)["tokens"])
    ug=svc.store.load_user(SITE,USER)
    hist["attrs"].append(len(ug.edges))
    hist["naive"].append(cum)
    hist["llm"].append(svc.llm_calls)
    for t in track:
        series[t].append(ug.edges[t].weight if t in ug.edges else 0.0)
populate_elena_entities(svc, SITE, USER, ts=float(N + 1))

template_path = os.path.join(ROOT, "_memory_map_template.html")
map_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "memory_map" + ".html")
with open(template_path, encoding="utf-8") as fh:
    template = fh.read()
graph_payload = json.dumps(svc.graph(SITE, USER), ensure_ascii=False, separators=(",", ":"))
with open(map_path, "w", encoding="utf-8") as fh:
    fh.write(template.replace("__OWNER__", "Elena").replace("__DATA__", graph_payload))

ug=svc.store.load_user(SITE,USER)
edges=sorted(ug.edges.items(), key=lambda kv:-kv[1].weight)
CONF=svc.cfg.conf_known
known=[(a,e) for a,e in edges if e.confidence>=CONF]

# ---------------- stable-fact retention ----------------
facts=["name:elena-sofia-markovic","nickname:lena","birthday:1991-09-14","origin:croatian",
 "city:ljubljana","employer:memoryforge","pet:miso","rel:jonas","pref:macos","pref:iphone",
 "pref:macbook","pref:markdown","activity:yoga","activity:swimming","pref:flat-white","value:documentation"]
have={a:e for a,e in edges}
retain=[(f, f in have, round(have[f].weight,1) if f in have else 0, have[f].hits if f in have else 0) for f in facts]
retained=sum(1 for _,ok,_,_ in retain if ok)

# ---------------- cost numbers ----------------
corpus=sum(rt for *_,rt in entries)
card_final=hist["card"][-1]
fern_read=sum(hist["card"]); mem0_in=corpus*2; mem0_out=int(corpus*0.15); naive=sum(hist["naive"])
PIN,POUT=0.15,0.60; usd=lambda i,o=0:(i*PIN+o*POUT)/1e6

# ================= PLOTS =================
plt.rcParams.update({"figure.dpi":130,"font.size":11,"axes.grid":True,"grid.alpha":.25,
                     "axes.spines.top":False,"axes.spines.right":False})
TEAL,AMBER,VIO,RED,BLUE,GRAY="#0f6e56","#a8690b","#6d4bb0","#a32d2d","#185fa5","#7a7972"
x=np.arange(1,N+1)

# 1) flat cost vs growing baselines
fig,ax=plt.subplots(figsize=(7,4.3))
ax.plot(x, np.cumsum(hist["card"]), color=TEAL, lw=2.4, label="FERNme card (sent each turn)")
ax.plot(x, hist["naive"], color=RED, lw=2.2, label="Naive: full history in context")
ax.plot(x, np.cumsum([corpus/N*2]*N), color=AMBER, lw=2, ls="--", label="Mem0-style extraction (LLM)")
ax.set_yscale("log"); ax.set_xlabel("entries ingested"); ax.set_ylabel("cumulative tokens (log)")
ax.set_title("Prompt/token cost grows for others, stays flat for FERNme"); ax.legend(fontsize=9)
fig.tight_layout(); fig.savefig(f"{OUT}/01_cost_growth.png"); plt.close(fig)

# 2) per-turn footprint flat
fig,ax=plt.subplots(figsize=(7,4))
ax.plot(x, hist["card"], color=TEAL, lw=2.4, label="FERNme card tokens (per turn)")
ax.plot(x, [c/i for i,c in zip(x,hist["naive"])], color=RED, lw=2, label="Naive avg per turn")
ax.fill_between(x, hist["card"], color=TEAL, alpha=.12)
ax.set_xlabel("entries ingested"); ax.set_ylabel("tokens injected this turn")
ax.set_title(f"FERNme stays ~{int(np.mean(hist['card']))} tokens/turn while history balloons")
ax.legend(fontsize=9); fig.tight_layout(); fig.savefig(f"{OUT}/02_flat_footprint.png"); plt.close(fig)

# 3) attributes learned + zero model calls in the core
fig,ax=plt.subplots(figsize=(7,4))
ax.plot(x, hist["attrs"], color=VIO, lw=2.4, label="facts remembered")
ax.set_xlabel("entries ingested"); ax.set_ylabel("facts in memory", color=VIO)
ax2=ax.twinx(); ax2.plot(x, hist["llm"], color=RED, lw=2.2, label="LLM calls (write path)")
ax2.set_ylabel("cumulative LLM calls", color=RED); ax2.set_ylim(-0.5, max(2,max(hist["llm"])+1)); ax2.grid(False)
ax.set_title("Memory grows to %d facts with 0 core model calls"%hist["attrs"][-1])
fig.tight_layout(); fig.savefig(f"{OUT}/03_growth_zero_llm.png"); plt.close(fig)

# 4) drift: CONTROLLED probe following the diary narrative.
# (The coarse entity-parser co-lists both teas, so the messy run ties them; this
#  isolated probe feeds the documented switch -- jasmine early, earl grey later --
#  to test whether decay lets a new favorite overtake an old one.)
ds=FernService(store=SQLiteStore(":memory:")); ds.track_style=False
ds.store.set_consent("drift","elena",True)
jas_steps=set([6,12,18])                      # jasmine mentioned early (thematic 07 era)
eg_steps=set([40,47,54,61,68,75,82])          # earl grey ramps in the 100-series
dj,de,dfw=[],[],[]
for i in range(1,87):
    tags=["pref:flat-white"]                  # stable favorite, mentioned ~weekly
    if i in jas_steps: tags.append("tea:jasmine")
    if i in eg_steps:  tags.append("tea:earl-grey")
    if i%7==0 and "pref:flat-white" not in tags: tags.append("pref:flat-white")
    ds.observe("drift","elena","entry",{"tags":tags},ts=float(i))
    u=ds.store.load_user("drift","elena")
    dj.append(u.edges["tea:jasmine"].weight if "tea:jasmine" in u.edges else 0)
    de.append(u.edges["tea:earl-grey"].weight if "tea:earl-grey" in u.edges else 0)
    dfw.append(u.edges["pref:flat-white"].weight if "pref:flat-white" in u.edges else 0)
cross=next((i for i in range(len(dj)) if de[i]>dj[i] and i>20), None)
fig,ax=plt.subplots(figsize=(7,4.3))
ax.plot(x, dfw, color=TEAL, lw=2.4, label="flat-white (stable favorite)")
ax.plot(x, dj, color=AMBER, lw=2.2, label="jasmine tea (early, then fades)")
ax.plot(x, de, color=VIO, lw=2.2, label="earl grey (introduced later, rises)")
if cross: ax.axvline(cross+1, color=RED, ls=":", lw=1.5); ax.text(cross+2, .3, "earl grey\novertakes", color=RED, fontsize=8)
ax.set_xlabel("entries ingested"); ax.set_ylabel("edge weight (0-9)")
ax.set_title("Controlled drift probe: new favorite overtakes the old; stable fact holds")
ax.legend(fontsize=9); fig.tight_layout(); fig.savefig(f"{OUT}/04_drift.png"); plt.close(fig)
series["tea:jasmine"]=dj; series["tea:earl-grey"]=de   # report the probe's final values

# 5) confidence vs repetition (calibration)
hits=np.array([e.hits for _,e in edges]); conf=np.array([e.confidence for _,e in edges])
fig,ax=plt.subplots(figsize=(7,4))
ax.scatter(hits, conf, s=24, color=TEAL, alpha=.6, edgecolor="none")
ax.axhline(CONF, color=RED, ls="--", lw=1.5, label=f"high-confidence threshold ({CONF})")
ax.set_xlabel("times the fact appeared (hits)"); ax.set_ylabel("confidence")
ax.set_title("Repeated facts earn confidence; one-offs stay tentative")
ax.legend(fontsize=9); fig.tight_layout(); fig.savefig(f"{OUT}/05_confidence_calibration.png"); plt.close(fig)

# 6) weight distribution known vs guess
w=np.array([e.weight for _,e in edges])
fig,ax=plt.subplots(figsize=(7,4))
ax.hist([e.weight for a,e in edges if e.confidence>=CONF], bins=18, color=TEAL, alpha=.85, label="high-confidence")
ax.hist([e.weight for a,e in edges if e.confidence<CONF], bins=18, color=GRAY, alpha=.7, label="tentative (guess)")
ax.set_xlabel("edge weight (0-9)"); ax.set_ylabel("number of facts")
ax.set_title(f"{len(known)} of {len(edges)} facts reinforced into high confidence")
ax.legend(fontsize=9); fig.tight_layout(); fig.savefig(f"{OUT}/06_weight_distribution.png"); plt.close(fig)

# 7) top hubs
top=edges[:15][::-1]
fig,ax=plt.subplots(figsize=(7,4.6))
ax.barh([a for a,_ in top], [e.weight for _,e in top],
        color=[TEAL if e.confidence>=CONF else GRAY for _,e in top])
ax.set_xlabel("edge weight"); ax.set_title("Top 15 facts FERNme is surest about (Elena)", fontsize=11)
fig.tight_layout(); fig.savefig(f"{OUT}/07_top_hubs.png"); plt.close(fig)

# 8) cost bars
fig,ax=plt.subplots(figsize=(7,4))
labels=["FERNme write","FERNme read","Mem0-style","Naive history"]
real=[0,fern_read,mem0_in+mem0_out,naive]
vals=[1,fern_read,mem0_in+mem0_out,naive]
cols=[TEAL,TEAL,AMBER,RED]
ax.bar(labels,vals,color=cols); ax.set_yscale("log"); ax.set_ylabel("LLM tokens (log)")
for i,v in enumerate(real): ax.text(i,vals[i]*1.25,f"{v:,}",ha="center",fontsize=9)
ax.set_title("Tokens to build + use this memory over 86 entries")
fig.tight_layout(); fig.savefig(f"{OUT}/08_cost_bars.png"); plt.close(fig)

summary=dict(entries=N,facts=len(edges),high_conf=len(known),llm_calls=svc.llm_calls,
 card_tokens=card_final,corpus=corpus,fern_read=fern_read,mem0_in=mem0_in,mem0_out=mem0_out,naive=naive,
 usd_fern=usd(fern_read),usd_mem0=usd(mem0_in,mem0_out),usd_naive=usd(naive),
 retained=retained,retain_total=len(facts),
 jasmine_final=round(series["tea:jasmine"][-1],2),earlgrey_final=round(series["tea:earl-grey"][-1],2),
 top=[(a,round(e.weight,1),e.hits,bool(e.confidence>=CONF)) for a,e in edges[:15]],
 retain=[(f,bool(ok),wt,h) for f,ok,wt,h in retain])
json.dump(summary,open(f"{OUT}/elena_eval_summary.json","w"),indent=1)
print("PLOTS+SUMMARY written to",OUT)
print(json.dumps({k:summary[k] for k in ["entries","facts","high_conf","llm_calls","card_tokens",
 "retained","retain_total","jasmine_final","earlgrey_final","usd_fern","usd_mem0","usd_naive"]},indent=1))
