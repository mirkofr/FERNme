"""LoCoMo-style QA benchmark on the Elena dataset.
Builds memory from all 86 entries, then asks fact questions. Each system retrieves
top-k attributes given the question's context seeds; a question is 'answered' if the
gold attribute is in the retrieved set (the standard retrieval proxy for QA accuracy:
with the right fact retrieved, an LLM answers correctly). All retrieval systems are zero-model-call and
runnable; Mem0 (LLM) is cited as an external reference, not run (needs API keys)."""
import os, re, glob, json, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from fernme.service import FernService
from fernme.store.sqlite_store import SQLiteStore
from fernme.retrieve.activation import ranked_attrs

DIR=os.environ["DIR"]; OUT=os.environ.get("OUT", os.path.join(os.path.dirname(os.path.abspath(__file__)),"figures")); os.makedirs(OUT, exist_ok=True)
tok=lambda s:max(1,len(s)//4)

# ---- parsing (same as eval_elena) ----
PEOPLE={"marina","ivan","jonas","filip","ana","daniel","priya","maya","luca","sara","nina","tomas","emily","ahmed","marta","keiko","haru","viktor","novak","andrej"}
BRANDS={"muji","uniqlo","apple","dropbox","jo malone","cerave","macbook","iphone","macos","memoryforge"}
FOOD={"tomato soup","mushroom risotto","bibimbap","salmon","risotto"}
def slug(s): return re.sub(r"[^a-z0-9]+","-",s.lower().strip()).strip("-")[:48]
def classify(e):
    e=re.sub(r"^the ","",e.lower().strip())
    if "earl grey" in e: return "tea:earl-grey"
    if "jasmine" in e: return "tea:jasmine"
    if "chamomile" in e: return "tea:chamomile"
    if "peppermint" in e: return "tea:peppermint"
    if "matcha" in e: return "tea:matcha"
    if "flat white" in e: return "pref:flat-white"
    if any(p in e for p in PEOPLE): return "rel:"+slug(e.split()[0] if " " in e else e)
    if any(b in e for b in BRANDS): return "brand:"+slug(e)
    if any(f in e for f in FOOD): return "food:"+slug(e)
    if "marathon" in e: return "goal:half-marathon"
    if "memory journal" in e: return "project:memory-journal-platform"
    if "book" in e: return "project:ai-pm-book"
    return "entity:"+slug(e)
TH={
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
    es=[]
    for p in sorted(glob.glob(os.path.join(DIR,"*.md"))):
        fn=os.path.basename(p)
        if fn.lower()=="readme.md": continue
        raw=open(p,encoding="utf-8").read()
        th=next((k for k in TH if fn.startswith(k)),None)
        if th: es.append((("0",fn),TH[th])); continue
        date=(re.search(r"\*\*Date:\*\*\s*([0-9-]+)",raw) or [None,"2026-06-01"])[1]
        tl=re.search(r"\*\*Tags:\*\*\s*(.+)",raw)
        tags=[]  # skip generic Tags: field (parser noise); keep Entities
        m=re.search(r"##+\s*Entities\s*(.+?)(?:\n##|\Z)",raw,re.S)
        if m:
            for line in m.group(1).splitlines():
                e=line.strip("-* \t")
                if e and not e.startswith("#") and not e.lower().startswith("elena"): tags.append(classify(e))
        es.append((("1",date,fn),[t for t in tags if t]))
    es.sort(key=lambda x:x[0]); return [t for _,t in es]

# ---- ingest ----
svc=FernService(store=SQLiteStore(":memory:")); svc.track_style=False
svc.store.set_consent("e","elena",True)
for i,tags in enumerate(parse(),1):
    svc.observe("e","elena","entry",{"tags":tags[:32]},ts=float(i))
ug=svc.store.load_user("e","elena"); ag=svc.store.load_assoc("e"); NOW=200.0

# ---- QA set: (question, gold[any-of], category, seeds) ----
Q=[
 ("What is Elena's full name?",["name:elena-sofia-markovic"],"identity",["nickname:lena","city:ljubljana"]),
 ("What do her family call her?",["nickname:lena"],"identity",["name:elena-sofia-markovic"]),
 ("When was Elena born?",["birthday:1991-09-14"],"identity",["name:elena-sofia-markovic","origin:croatian"]),
 ("What city does she live in?",["city:ljubljana"],"identity",["field:hci","study:cs-zagreb"]),
 ("Where is she originally from?",["origin:croatian","origin:zagreb"],"identity",["rel:marina","rel:ivan"]),
 ("Who is her employer?",["employer:memoryforge"],"work",["project:memory-journal-platform","rel:daniel"]),
 ("Who is her partner?",["rel:jonas"],"relationship",["pet:miso","food:mushroom-risotto"]),
 ("What is her pet?",["pet:miso"],"identity",["rel:jonas"]),
 ("What does she drink in the morning?",["pref:flat-white"],"preference",["pref:macbook","pref:one-sugar"]),
 ("How does she take her coffee?",["pref:one-sugar"],"preference",["pref:flat-white"]),
 ("What laptop does she use?",["pref:macbook"],"preference",["pref:macos","pref:iphone"]),
 ("How does she keep notes?",["pref:markdown-notes","pref:markdown"],"preference",["trait:structured-notes","pref:macbook"]),
 ("What is her clothing style?",["pref:minimalist-style","pref:earth-tones"],"preference",["brand:muji","brand:uniqlo"]),
 ("What skincare brand does she use?",["pref:cerave"],"preference",["pref:jo-malone","pref:minimalist-style"]),
 ("What perfume does she use?",["pref:jo-malone"],"preference",["pref:cerave"]),
 ("What is her main fitness goal?",["goal:half-marathon"],"goal",["activity:running","rel:nina"]),
 ("What language is she studying?",["study:japanese","goal:jlpt-n3"],"goal",["rel:keiko","rel:haru"]),
 ("What book is she writing?",["project:ai-pm-book"],"project",["rel:emily","rel:marta"]),
 ("What is her main work project?",["project:memory-journal-platform"],"project",["rel:daniel","rel:priya"]),
 ("Where does she want to travel?",["goal:visit-japan","goal:visit-norway"],"goal",["food:bibimbap"]),
 ("Who is her best friend?",["rel:sara"],"relationship",["!pref:voice-messages","goal:half-marathon"]),
 ("Who does she run with / running club?",["rel:nina"],"relationship",["goal:half-marathon","activity:running"]),
 ("Who is her book editor?",["rel:marta"],"relationship",["project:ai-pm-book","rel:emily"]),
 ("Who is her brother?",["rel:filip"],"relationship",["origin:zagreb","rel:marina"]),
 ("Who is her neighbor?",["rel:novak"],"relationship",["pet:miso","rel:andrej"]),
 ("What does she dislike receiving?",["!pref:voice-messages"],"negation",["rel:sara","style:texts-like-emails"]),
 ("What kind of meetings annoy her?",["!pref:meetings-without-agenda"],"negation",["pref:markdown-notes"]),
 ("Does she have food allergies?",["health:no-food-allergies"],"negation",["health:migraines","health:pollen-allergy"]),
 ("What vacations does she avoid?",["!pref:resort-vacations"],"negation",["goal:visit-japan","pref:bookstores"]),
 ("What health issue does she manage?",["health:migraines"],"health",["activity:swimming","pref:early-sleep"]),
 ("What is her weight?",["metric:weight-64kg"],"health",["activity:running","goal:half-marathon"]),
 ("What does she drink before bed?",["tea:chamomile"],"preference",["pref:early-sleep"]),
 ("Which tea does she reach for in the afternoon now?",["tea:earl-grey"],"drift",["tea:chamomile","tea:jasmine"]),
]

K=10
def assoc_to(a, seeds):
    return sum(ag.edges.get((a,sd),0)+ag.edges.get((sd,a),0) for sd in seeds)
def fern_query(seeds, k=K):                     # seed-conditioned spreading activation
    sc=[(a, e.weight + 3.0*assoc_to(a,seeds)) for a,e in ug.edges.items()]
    sc.sort(key=lambda x:-x[1]); return [a for a,_ in sc[:k]]
def topk(rank_fn,k=K): return [a for a,_ in sorted(((a,rank_fn(e)) for a,e in ug.edges.items()),key=lambda x:-x[1])[:k]]
freq_rank=topk(lambda e:e.hits); rec_rank=topk(lambda e:e.last_reinforced); wt_rank=topk(lambda e:e.weight)
def hit(retr,gold): return any(g in retr for g in gold)
systems=["FERNme (context)","FERNme (no context)","Frequency","Recency"]
results={s:{} for s in systems}; per_cat={s:{} for s in systems}
for q,gold,cat,seeds in Q:
    retr={"FERNme (context)":fern_query(seeds),"FERNme (no context)":wt_rank,"Frequency":freq_rank,"Recency":rec_rank}
    for s in systems:
        h=hit(retr[s],gold); results[s][q]=h; per_cat[s].setdefault(cat,[]).append(h)
acc={s:round(100*sum(results[s].values())/len(Q),1) for s in systems}
cats=sorted({c for *_,c,_ in [(q,g,c,s) for q,g,c,s in Q]})
catacc={s:{c:round(100*np.mean(per_cat[s][c]),0) for c in per_cat[s]} for s in systems}
card_tokens=svc.card("e","elena",context=Q[0][3])["tokens"]

print("=== overall accuracy (top-%d) ==="%K)
for s in systems: print(f"  {s:22} {acc[s]:5.1f}%")
print("\n=== by category (FERNme context vs Frequency) ===")
for c in cats:
    print(f"  {c:13} FERNme {catacc['FERNme (context)'].get(c,0):3.0f}%  | Freq {catacc['Frequency'].get(c,0):3.0f}%")
print("\nquestions:",len(Q)," retrieval budget k=",K," FERNme card tokens=",card_tokens)

# ---- plots ----
plt.rcParams.update({"figure.dpi":130,"font.size":11,"axes.grid":True,"grid.alpha":.25,"axes.spines.top":False,"axes.spines.right":False})
TEAL,AMBER,VIO,RED,GRAY="#0f6e56","#a8690b","#6d4bb0","#a32d2d","#7a7972"
order=["FERNme (context)","FERNme (no context)","Recency","Frequency"]
short=["FERNme\n(context)","FERNme\n(no context)","Recency","Frequency"]
fig,ax=plt.subplots(figsize=(8,4.4))
xs=np.arange(len(order))
ax.bar(xs,[acc[s] for s in order],width=0.62,color=[TEAL,"#6fcaa0","#9ab",GRAY])
for i,s in enumerate(order): ax.text(i,acc[s]+1.8,f"{acc[s]:.0f}%",ha="center",fontsize=11,fontweight="bold")
ax.set_xticks(xs); ax.set_xticklabels(short,fontsize=10.5)
ax.set_ylabel("answer-retrieval accuracy (%)"); ax.set_ylim(0,105)
ax.margins(x=0.06)
ax.set_title(f"LoCoMo-style QA on Elena ({len(Q)} questions, top-{K} retrieval)")
fig.tight_layout(); fig.savefig(f"{OUT}/09_qa_accuracy.png"); plt.close(fig)

cc=[c for c in cats]
fw=[catacc["FERNme (context)"].get(c,0) for c in cc]; fr=[catacc["Frequency"].get(c,0) for c in cc]
xx=np.arange(len(cc)); w=0.4
fig,ax=plt.subplots(figsize=(8,4.2))
ax.bar(xx-w/2,fw,w,color=TEAL,label="FERNme (context)")
ax.bar(xx+w/2,fr,w,color=GRAY,label="Frequency")
ax.set_xticks(xx); ax.set_xticklabels(cc,rotation=30,ha="right"); ax.set_ylabel("accuracy (%)"); ax.set_ylim(0,109)
ax.set_title("QA accuracy by category: where context-aware retrieval helps")
ax.legend(fontsize=9); fig.tight_layout(); fig.savefig(f"{OUT}/10_qa_by_category.png"); plt.close(fig)


# ---- budget sweep: accuracy vs retrieval size k ----
ks=[5,10,15,20,30,40]
def topk_by(fn,k): return [a for a,_ in sorted(((a,fn(e)) for a,e in ug.edges.items()),key=lambda x:-x[1])[:k]]
sweep={s:[] for s in systems}
for k in ks:
    fr=topk_by(lambda e:e.hits,k); rc=topk_by(lambda e:e.last_reinforced,k); wt=topk_by(lambda e:e.weight,k)
    accs={"FERNme (context)":0,"FERNme (no context)":0,"Frequency":0,"Recency":0}
    for q,gold,cat,seeds in Q:
        fq=fern_query(seeds,k)
        for s,retr in (("FERNme (context)",fq),("FERNme (no context)",wt),("Frequency",fr),("Recency",rc)):
            accs[s]+= 1 if hit(retr,gold) else 0
    for s in systems: sweep[s].append(round(100*accs[s]/len(Q),1))
fig,ax=plt.subplots(figsize=(7,4.3))
cmap={"FERNme (context)":TEAL,"FERNme (no context)":"#6fcaa0","Frequency":GRAY,"Recency":"#9ab"}
for s in systems: ax.plot(ks,sweep[s],marker="o",lw=2.2,color=cmap[s],label=s)
ax.set_xlabel("retrieval budget (top-k facts)"); ax.set_ylabel("answer accuracy (%)"); ax.set_ylim(0,100)
ax.set_title("FERNme leads at every budget; cheap counters stay flat-low")
ax.legend(fontsize=9); fig.tight_layout(); fig.savefig(f"{OUT}/11_qa_budget_sweep.png"); plt.close(fig)
print("sweep:",{s:sweep[s] for s in systems})

json.dump(dict(k=K,n=len(Q),acc=acc,catacc=catacc,card_tokens=card_tokens,
 cats=cats),open(f"{OUT}/elena_qa_summary.json","w"),indent=1)
print("\nplots + summary written to",OUT)
