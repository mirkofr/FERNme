# Testing FERNme — a 15-minute eval recipe

> Long-term memory needs **failure examples more than praise**. This recipe is
> built to *break* FERNme on purpose and tell us where. If you run even half of
> it and report what it does wrong, that's the most useful feedback we can get.

The point of FERNme isn't to recall every line you ever said — it's to keep a
small, inspectable model of a person that **strengthens, decays, becomes
uncertain, flags contradictions, and connects related memories**. So we don't
test it like a search box. We seed a profile, age it, contradict it, and then
ask it what it is *certain* about and *why*.

---

## 0. Setup (pick one surface)

All three drive the same engine. Use whichever matches how you'd actually run it.

**A) As an MCP tool (Claude Desktop / any MCP agent) — closest to real use**

```bash
pip install fernme
python -m fernme.api.mcp_server      # exposes: remember, recall_card,
                                     # recall_events, recall_glossary,
                                     # grant_consent, edit_memory, forget_me
```

**B) Python, directly**

```python
from fernme.service import FernService
svc = FernService(db_path=":memory:")     # throwaway DB — never test on a real one
svc.consent("demo.shop", "tester", True)
```

**C) REST**

```bash
FERNME_API_KEY=secret uvicorn fernme.api.rest:app --port 8077
# /observe /card /recall /edit /why /export /delete /triggers ; UI at /ui , graph at /graph
```

Conventions below use `site="demo.shop"`, `user="tester"`. **Use a fresh/empty
DB.** Don't point the recipe at a profile you care about.

### Real-profile copy validator

For local validation on a copied SQLite profile, use:

```bash
python scripts/validate_real_profile.py --db copied_profile.db --site demo.shop --user tester --entity-map local_entity_map.yaml
```

The script copies the supplied DB to a temporary file before doing any entity
work. Default output is redacted: candidate alias clusters are reported by size
and score only, and probe relation checks are yes/no by probe id. Local mapping
files matching `*_entity_map.yaml` are gitignored. Filenames starting with
`mirko` are refused unless you pass `--i-am-the-owner-on-a-copy`; use that only
for a copy, never the live DB.

Importer bookkeeping namespaces -- import ids, file paths, section markers, and
similar source-tracking tags -- should be added to `cfg.card_exclude_ns` so they
stay queryable in the profile without spending compact-card slots.

---

## 1. Seed ~20 memories — deliberately mixed by how fast they should rot

Decay is only testable if some facts *should* age and others shouldn't. Mark
what you *state* as `source="stated"` and what an agent would *guess* as
`source="inferred"` — that distinction drives the contradiction behavior in §3.

| bucket | example memory | why it's here |
|---|---|---|
| **permanent** | `allergy:peanuts`, `name:sister=Mara`, `birthday:apr-3` | must stay high-confidence forever |
| **slow** | `pref:employer=Acme`, `context:city=Berlin`, `pref:role=designer` | plausibly stale in a year, not a day |
| **volatile** | `context:current_project=atlas`, `context:traveling=true`, `pref:closest_friend=Tom` | should lose confidence fast |
| **stable taste** | `pref:concise`, `pref:oat_milk`, `!likes:dairy`, `topic:python` | the bread-and-butter recall case |
| **events** | `did:ordered_sushi`, `did:booked_flight` | timestamped; should *not* decay like a standing fact |

Example call (MCP tool form):

```text
remember(site="demo.shop", user="tester", type="pref",
         tags=["pref:oat_milk", "!likes:dairy"],
         text="I take oat milk, I avoid dairy.", source="stated")

remember(site="demo.shop", user="tester", type="context",
         tags=["context:current_project=atlas"],
         text="Right now I'm on the Atlas project.", source="stated")
```

Add ~20 across the buckets. Vary timestamps if you can (`ts=`) so some are old.

---

## 2. Confirm baseline recall

```text
recall_card(site="demo.shop", user="tester")          # the token-minimal card
recall_glossary(site="demo.shop", user="tester")      # what each tag means + its source sentence
```

**Watch for:**
- Does the card hold the *stable tastes and constraints*, not noise?
- Is the card still small (~tens of tokens), not a dump of all 20 memories?
- Does the glossary correctly show what each tag means and the sentence it came from?

---

## 3. Introduce 3 contradictions — three different flavors

This is the core test. FERNme's stance: **inferred memory never silently
overrides stated memory; a conflict returns a `questions` / `superseded` list
instead of overwriting.** Verify that.

1. **Direct clash (stated → contradicting action).** Stored `!likes:dairy` /
   `pref:oat_milk`, then:
   ```text
   remember(... tags=["likes:dairy", "pref:whole_milk"],
            text="Get me a whole-milk latte.", source="inferred")
   ```
   **Pass:** the call returns a `questions`/`superseded` entry (it *asks*, doesn't
   silently flip). **Fail:** it overwrites the dairy preference with no flag.

2. **Silent swap (no contradiction surfaces).** Change a *slow* fact without ever
   marking the old one wrong — e.g. set `pref:employer=Globex` after
   `pref:employer=Acme`, both `stated`, months apart.
   **Watch:** does the old value get marked superseded / lose confidence, or do
   both sit there? Does `recall_card` now confidently return the new one?

3. **Partial / soft conflict.** `pref:closest_friend=Tom` earlier, then lots of
   activity about someone else as "closest." No hard contradiction — just drift.
   **Watch:** does the older claim fade relative to the newer one, or stay equal?

---

## 4. Age it / force decay, then re-read

Let the volatile memories decay (advance `now=`/`ts=`, or call the service after
time has passed; the class-targeted retention layer is **on by default**), then:

```text
recall_card(site="demo.shop", user="tester")
recall_events(site="demo.shop", user="tester", contains="employer")   # the Cabinet: nothing is deleted, just down-weighted
```

**Watch for the failure mode we most expect:**
- Do the **permanent** facts (allergy, sister's name) stay high-confidence while
  the **volatile** ones (current_project, traveling) drop? If *everything* decays
  at the same rate, that's a **fail** — the class-targeted retention layer should
  keep permanent facts durable while letting current/volatile facts fade quickly.
- After decay, can you still find the old value via `recall_events`? Nothing
  should be hard-deleted — only down-weighted.

---

## 5. The final probe — "what are you certain about, and why?"

Ask the agent (or call `why(user, attr)` / the REST `/why` endpoint) to explain
what it's confident about and on what evidence.

**Pass looks like:**
- It can name *which* memories it trusts and distinguish **stated vs inferred**
  provenance ("you told me X" vs "I guessed X from behavior").
- It surfaces the contradictions from §3 as open questions rather than silently
  having picked a side.
- Confidence tracks the buckets: high on permanent, lower on aged-volatile.

**Fail looks like:**
- Equal confidence in a peanut allergy and a 60-day-old "current project."
- It "knows" something it only *inferred*, with no provenance.
- A contradiction was resolved by silent overwrite, with no trace.

---

## The honest hard case (report this one especially)

The case we **do not** solve today: a *slow* fact that goes stale with **no
contradiction and no new evidence** — someone changes jobs and never mentions it.
Nothing conflicts, so age-only verify stays off by default. FERNme can flag
genuine contradictions and retain permanent facts, but it cannot reliably detect
silent staleness in a fact that produces no signal.
If §3.2 or §4 shows FERNme confidently acting on a stale slow-fact, that's
expected — and exactly the report we want, because the next design problem is
learned per-edge volatility or outside corroboration.

---

## How to report

Open an issue at **github.com/mirkofr/FERNme** with:

1. Which step broke (e.g. "§3.1 overwrote silently").
2. The exact calls you made.
3. What you expected vs. what happened (paste the `recall_card` / `questions` output).

Failure reports > stars. Thanks for kicking the tires.
