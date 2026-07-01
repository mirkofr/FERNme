# Build spec: Volatility-typed memories (Option A + C)

**Audience:** the implementing agent (Codex).
**Status:** approved design, not yet built. Implement behind a flag; do not push.
**Companion docs:** `resolution.py` docstring, `v0.3.3_persistence_spec.md`, `AGENTS.md`, `CODEX_RULES.md`.

Read this whole file before writing code. It explains **why** we're doing this,
**what** to build, **how**, and **what for**, so you can make good local
decisions. Treat the existing code and tests as the source of truth; if anything
here contradicts the code, stop and flag it rather than guessing.

---

## 1. Why this exists (the problem)

FERNme decays every memory at the **same global rate** (`Config.lam = 0.02/day`,
a ~35-day half-life). That is wrong, because memories don't go stale at the same
speed:

- A **peanut allergy** or a person's **name** should essentially never lose confidence.
- An **employer** or **home city** is plausibly true for ~a year, not forever.
- A **current project** or "**traveling right now**" is suspect within weeks.

With one global rate you can't win: set it short and permanent facts rot (you
nag the user about things that never change, burning their trust); set it long and
volatile facts stay falsely confident (the agent acts on "current project = Atlas"
months after it changed). **The decay rate has to depend on the *kind* of fact —
specifically on how fast that kind of thing changes in the real world.** That
property is its *volatility*.

### What this is *for* (the downstream goal)

This is not just a decay tweak. The real product goal (from user research and a
long public design discussion) is: **FERNme should describe how reliable each
memory is, so the agent can decide whether to just use it or verify it first.**

The agent layer (out of scope here) combines FERNme's reliability signal with the
*stakes* of what it's about to do — e.g. an outdated employer is harmless in
chat but risky on a legal form or a travel booking. FERNme's job is only the
**"is this memory still trustworthy?"** half. Today FERNme can't answer that well
because its confidence/recency signal ignores volatility: a 60-day-old "current
project" looks exactly as fresh as a 60-day-old allergy. Option C fixes that and
emits an explicit `verify` flag. Option A makes the underlying decay honest.

We are deliberately **not** building per-edge learned volatility (Option B) or any
stakes/operation logic in this pass — see §10.

---

## 2. What already exists (extend it, don't rebuild)

Most of the machinery is present but unpopulated and off by default. Your job is
largely to fill it in and wire it through, not invent new structure.

- **`resolution.py`** already defines a volatility axis via `species_of(attr)` →
  `fact | project | habit | style | preference | association`, and already has
  `species_multiplier(attr, cfg)` reading `cfg.species_decay`, and
  `lambda_eff(attr, edge, ...) = cfg.lam * temperature(...) * species_multiplier(...)`.
  This axis is **correctly orthogonal** to `categories.py` (which is the *semantic*
  axis: people / facts / media…). Keep them separate. Volatility ≠ topic.
- **`write/hebbian.py::decay()`** already branches: when `cfg.resolution` is true
  it decays each edge by `lambda_eff`; otherwise it uses the flat
  `lam * (1 - salience_beta * salience)`. So per-edge decay rates are already
  plumbed — they're just all 1.0 because `cfg.species_decay` is an **empty dict**.
- **`core/graph.py::Edge`** already carries `salience` (slows forgetting), `fast`
  + `lam_fast` (a fast/recent timescale), `hits`, `last_reinforced`, `history`.
- **`identity.py::is_identity_attr`** + `cfg.identity_sticky` already floor certain
  namespaces so they don't drop out of the card.
- **`confidence.py::compute()`** blends evidence/consistency/taxonomy/recency/outcome
  into a 0–1 confidence — but its `recency` term uses the **global** `cfg.lam`, not
  the volatility-aware rate. This is the gap Option C closes.

The net change is small: populate the volatility table, refine the class mapping so
it's granular enough, make confidence volatility-aware, and add a `verify` flag.

---

## 3. Scope of this task

**In scope:** Step 0 (provenance fix, a precondition), Option A (volatility-typed
decay), Option C (volatility-aware confidence + `verify` flag).

**Behind a flag.** All new behavior must be **off by default** so existing tests
and benchmark numbers are unchanged. Reuse the existing `Config.resolution` flag
(Option A already lives under it) and add `Config.volatility_confidence` for
Option C. With flags off, behavior is byte-for-byte the current behavior.

**Out of scope (do not build):** Option B (per-edge *learned* half-lives + DB
migration), any stakes/operation-spec/agent-side logic, embeddings.

---

## 4. Invariants you must not break

These are core FERNme guarantees. A change that violates one is wrong even if tests pass.

1. **Zero LLM in the write path.** All of this is arithmetic on the graph. No model calls, no vector search, in `observe` or `decay`.
2. **Bounded/flat cost.** Don't add per-turn work that grows with profile size beyond the existing O(edges) decay pass. No new token cost in the card beyond a tiny per-edge flag.
3. **Injection safety.** Stored tags/text are untrusted data. Nothing here may let stored text change a decay rate, provenance, or the `verify` decision in an attacker-controlled way.
4. **Consent / per-site isolation / deletion** unchanged.
5. **Backwards compatible & reversible.** Flags default off → identical behavior. No DB migration in this task (that's Option B).
6. **Honesty.** Any new quality claim must come from the validation harness in §9, run for real. Don't assert it works without running it. Simulated results are labeled synthetic.

---

## 5. Step 0 — Fix provenance propagation (precondition, do this first)

**The bug.** `service.observe()` reads `new_source = payload.get("source", "known")`
(the `stated`/`inferred` the agent sent), but `write/hebbian.py::observe()`
hardcodes `e.source = "known"`. So the edge **never stores whether a fact was
stated by the user or inferred by the agent.** Meanwhile:

- `resolution.py::resolution()` gives the big explicit-evidence weight
  (`res_w_explicit = 0.35`) only when `edge.source in {"override", "stated"}` —
  but edges are never `"stated"`, so this never fires for normal writes.
- `confidence.py::compute()` sets `taxonomy = 0.4` when `edge.source == "guessed"`
  — but edges are never `"guessed"` either.

So provenance is invisible to exactly the two functions volatility depends on.
The authority/curation path *does* use `new_source` correctly at write time
(`curation._AUTH`), but the edge forgets it afterward.

**The fix (minimal, non-breaking).** Keep `Edge.source` for *lifecycle*
(`known | override | superseded`) and add a **separate provenance field**:

- In `core/graph.py`, add to `Edge`: `provenance: str = "inferred"`  # "stated" | "inferred"
- In `write/hebbian.py::observe()`, accept the provenance for each write and set
  `e.provenance = "stated"` when the incoming source is `stated`/`override`, else
  `"inferred"`. Never downgrade an existing `"stated"` to `"inferred"` (stated is
  sticky provenance; a later inferred reinforcement keeps it stated).
- In `service.observe()`, pass `new_source` through to the write so provenance lands on the edge.
- Update `resolution.py` to read `edge.provenance == "stated"` (or `edge.source == "override"`) for the explicit axis.
- Update `confidence.py` to use `edge.provenance == "inferred"` for the low-taxonomy default.

**Do not** persist `provenance` to the DB store in this task (no migration). It's
an in-memory field defaulting to `"inferred"`; on load, unknown → `"inferred"`.
(Persistence is folded into Option B later.) Note this limitation in the docstring.

Add a unit test proving a `stated` `remember` results in `edge.provenance == "stated"`
and an `inferred` one in `"inferred"`.

---

## 6. Step A — Volatility-typed decay

### 6.1 Define one source of truth for volatility classes

The current `species_of` is too coarse: it lumps `name` (permanent) and `employer`
(slow) both into `fact`. Refine it so permanence and slowness are distinct.

In `resolution.py`, define explicit classes and the namespaces that map to them
(extend the existing `*_NAMESPACES` sets; keep `species_of` as the public function):

| volatility class | namespaces (examples) | meaning |
|---|---|---|
| `permanent` | name, birthday, origin, nationality, lang, allergy, milestone, event | once true, ~always true |
| `slow` | employer, company, city, role, position, affiliation, status, domain | changes over ~a year |
| `preference` | pref, likes, diet, food, value, goal | stable taste, can drift |
| `habit` | habit, cadence, activity, tool | changes over months |
| `volatile` | project, deadline, context, traveling, `current_*` | changes in weeks |
| `style` | mood, style | handled by the fast lane; treat as default |
| `association` | everything else (default) | generic |

Keep `categories.py` untouched — that's the semantic axis and is used by the UI/map.

### 6.2 Populate the half-lives → multipliers

Decay is `weight *= exp(-lam_eff * dt)`. The base `lam = 0.02/day` ⇒ base
half-life `ln(2)/0.02 ≈ 34.7 days`. The species multiplier scales it:
`lam_eff = lam * multiplier` ⇒ `half_life_eff = 34.7 / multiplier`. So:
`multiplier = 34.7 / target_half_life_days`.

Set `Config.species_decay` defaults to:

| class | target half-life (days) | multiplier |
|---|---|---|
| permanent | ~3650 | 0.01 |
| slow | ~200 | 0.17 |
| preference | ~120 | 0.29 |
| habit | ~90 | 0.39 |
| volatile | ~14 | 2.48 |
| style | (default) | 1.0 |
| association | ~35 | 1.0 |

Put the **half-lives** in config as the human-readable knob and derive the
multipliers from them in one helper (so future tuning edits days, not magic
multipliers). Document the `lam`-relative math next to it.

### 6.3 Reconcile with identity stickiness

`is_identity_attr` currently includes `employer`/`city`/`role`. Stickiness means
"don't drop from the card," which is about *retention*, not *freshness*. Keep
stickiness for genuinely permanent identity (name, birthday, origin) but **a
sticky-but-slow fact must still be allowed to lose confidence and trigger `verify`
(Step C).** Concretely: stickiness may floor the *weight* so the edge survives,
but it must **not** floor confidence or reset the volatility clock. Make sure a
stale employer still reports low confidence / `verify=true` even though it stays
in the card. Add a test for exactly this case.

### 6.4 Turn it on under the flag

Option A rides the existing `cfg.resolution` flag (default `False`). With it off,
`species_decay` may be populated but `decay()` takes the flat branch, so nothing
changes. With it on, edges decay by class. Confirm the existing resolution unit
tests still pass.

---

## 7. Step C — Volatility-aware confidence + a `verify` signal

### 7.1 Make confidence volatility-aware

In `confidence.py::compute()`, the `recency` term currently is
`exp(-cfg.lam * (now - last_reinforced))`. Behind a new flag
`Config.volatility_confidence` (default `False`), replace `cfg.lam` with the
edge's effective rate for the *recency* term only:
`exp(-lam_eff(attr, edge, ...) * dt)`. Reuse `resolution.lambda_eff` (or a thin
wrapper that doesn't require the full resolution machinery to be on — confidence
should be able to use volatility even if temperature decay is off; gate cleanly so
the two flags are independent). Effect: volatile facts lose the recency component
fast; permanent facts barely lose it. Everything else in `compute()` stays.

### 7.2 Emit a `verify` flag

Add a pure helper (e.g. `resolution.needs_verify(attr, edge, now, cfg)` or in a new
`verify.py`) returning a small structured result:

```
{ "verify": bool, "reason": str, "age_halflives": float, "confidence": float }
```

Rule (deterministic, no LLM):

- `verify = False` if `edge.source == "override"` (user locked it — never nag).
- otherwise `age_halflives = dt / half_life(class_of(attr))`.
- `verify = True` when `age_halflives >= cfg.verify_age_halflives` (default ~1.5)
  **and** `edge.provenance != "stated"` OR `age_halflives >= cfg.verify_age_halflives_stated`
  (a higher bar for user-stated facts, default ~3.0 — we trust what the user told us longer).
- `reason` is a short string like `"stale: 2.1 half-lives, slow fact"`.

This is **reliability only**. Do not encode stakes, do not decide whether to ask —
that's the agent's job. Just expose the signal.

### 7.3 Surface it where the agent can read it

- `service.card()` / `retrieve/card.py`: add an optional per-entry `verify`
  field (only when `volatility_confidence` is on). Keep the wire card small —
  a boolean per flagged edge, not a paragraph. Do not bloat the ~25-token card for
  the common (non-stale) case; only annotate edges that are actually flagged.
- `service.why()`: include `age_halflives` and `verify` in the explanation output,
  since `why` is the human/agent-facing "should I trust this?" surface.

Add tests: a fresh volatile edge → `verify=False`; the same edge aged past the
threshold → `verify=True`; an `override` edge aged arbitrarily → `verify=False`;
a `stated` permanent fact aged a year → `verify=False`.

---

## 8. Config additions (summary)

Add to `Config` (all defaulting to current/off behavior):

- `species_decay` — populate defaults per §6.2 (derive from half-lives).
- `volatility_half_lives: dict` — the human-readable days per class (source of truth).
- `volatility_confidence: bool = False` — gate for §7.1.
- `verify_age_halflives: float = 1.5`
- `verify_age_halflives_stated: float = 3.0`

Document each with a one-line comment, matching the existing config style.

---

## 9. Validation (run it for real; report numbers)

Extend `eval/drift.py` (or add `eval/volatility.py`) to build a **mixed-volatility
population**: each simulated user has some attrs that change fast, some slow, some
never. Compare **control** (flags off, flat decay) vs **treatment** (flags on):

1. **No regression on stable facts:** precision@5 on permanent/preference attrs must not drop vs control.
2. **Faster forgetting of stale-volatile facts:** volatile attrs that stopped being reinforced should fall below `floor` (or below the new value) materially sooner than under flat decay.
3. **Staleness metric (the headline):** fraction of edges that are *high-confidence but wrong* at "action time" — treatment should lower this vs control.
4. **Verify precision/recall:** of edges the sim knows are stale, what fraction get `verify=True` (recall) and what fraction of `verify=True` are actually stale (precision). Report both; the nag/false-positive rate matters.

Multi-seed; print mean ± std like the other eval modules. **Label all of it
synthetic.** Provide a reproduce command, e.g. `python -m fernme.eval.volatility`.

Also run the full suite: `pytest -q` (currently 119 passing, 2 skipped) — must stay green with flags off.

---

## 10. Out of scope (next milestones, do not build now)

- **Option B — per-edge learned half-lives.** Persisting volatility, learning it
  from observed change frequency, and the DB migration. Two known traps to design
  for later: right-censoring (you only observe changes, not non-changes, so long
  stability must read as *low* volatility) and gaming (only count `stated`/`override`
  changes toward volatility, never `inferred`).
- **Stakes / operation preconditions / agent ask-logic.** FERNme stays
  reliability-only; the agent owns "should I use it here."

---

## 11. Deliverables & house rules

- **Files you'll likely touch:** `core/graph.py` (Edge.provenance), `write/hebbian.py`
  (observe provenance + decay already branches), `service.py` (pass source; card/why
  surfacing), `resolution.py` (classes, half-life helper, `needs_verify`),
  `confidence.py` (volatility-aware recency), `config.py` (new knobs),
  `retrieve/card.py` (verify field), `eval/` + `tests/`.
- **Do not** modify `categories.py`'s semantic mapping, run any DB migration, or
  touch `mirko.db` or any real database — develop against `:memory:` / fixtures only.
- **Do not commit, push, tag, or publish.** Leave changes staged; this ships in one
  commit together with `TESTING.md` and the README badge.
- **When done, report (per CODEX_RULES):** what changed, why, files changed, the
  exact test/eval commands you ran and their real results, and remaining
  limitations (notably: provenance is in-memory only until Option B adds persistence).

## 12. Acceptance criteria

- With both flags **off**: `pytest -q` identical to baseline (119 pass / 2 skip); benchmark numbers unchanged.
- With flags **on**: permanent facts retain confidence over long spans; volatile facts decay fast; a stale-but-sticky employer stays in the card yet reports `verify=true`; `override` never flags.
- Provenance round-trips: `stated` remember → `edge.provenance == "stated"`.
- `eval/volatility` runs, prints multi-seed mean ± std, and shows treatment beating control on the staleness metric without regressing stable recall.
- New behavior is fully behind flags and documented in config + the resolution docstring.

---

# Revision addendum R1 (post first pass)

The first implementation (Option A + C) is functionally correct and tests pass
(focused 14, full suite 134 passed / 2 skipped, flags default off). The items
below are required revisions before any volatility number is used in a claim,
README, or checkpoint. None is a rewrite; they tighten correctness and make the
eval actually informative.

## R1.1 Rebuild `eval/volatility.py` as a real distribution (highest priority)

The current eval uses a single inferred stale fact copied deterministically, so
`stale_high_conf_wrong = 1.000/0.000` and `verify precision/recall = 1.000/1.000`
are artifacts of construction, not evidence. Most importantly it contains **zero
"old but still true" facts**, so the false-positive (nag) rate is forced to 0 --
the one number that decides whether the feature is usable is unmeasured.

Rebuild the population so each simulated user has a **mix**, with randomized ages
that straddle the verify thresholds:

- Several facts per volatility class (permanent, slow, preference, habit, volatile).
- **Old-but-still-true** facts (both `stated` and `inferred`) that have NOT changed
  -- these are the ground-truth negatives. Any `verify=True` on them is a false
  positive / nag. Report a **nag rate** = fraction of still-true facts flagged.
- **Genuinely stale** facts (value changed, old one not reinforced) -- ground-truth
  positives for recall.
- **Recently reinforced volatile** facts -- must NOT flag (regression guard).
- Use a production-like `floor` (the default `floor=1.0`), not `floor=0.0`, OR run
  both regimes and report which; do not silently use a non-default floor.

Report, multi-seed (mean +/- std), control (flags off) vs treatment (flags on):

1. **stable recall p@5** -- treatment must not regress vs control.
2. **stale-high-confidence-wrong** -- treatment lower than control (the headline).
3. **verify recall** -- of truly stale facts, fraction flagged.
4. **verify precision AND nag rate** -- of flagged facts, fraction truly stale;
   and of still-true facts, fraction wrongly flagged. These must be < 1.0 / > 0.0
   for the eval to be meaningful; if they come out perfect, the fixture is still
   too easy -- add noise and overlap until they don't.

## R1.2 Sweep the verify thresholds; treat current values as provisional

`verify_age_halflives` (1.5) and `verify_age_halflives_stated` (3.0) are guesses
and interact multiplicatively with each class half-life. Consequences to check:
an **inferred preference flags at ~180 days even if still true** (possible
over-nag); a **stated slow fact like employer only flags at ~600 days** (possibly
too lenient). In the eval, sweep both thresholds over a small grid and print the
recall-vs-nag-rate trade-off so a defensible default can be chosen from data, not
assumed. Until then, do not present 1.5/3.0 as validated.

## R1.3 Collapse the two decay sources of truth

Both `Config.volatility_half_lives` and `Config.species_decay` exist, and
`species_multiplier` prefers the half-lives dict, falling back to `species_decay`
-- but `species_decay` is itself derived from the half-lives at construction. So
editing `species_decay` directly is silently ignored. Make
`volatility_half_lives` the single stored knob and compute multipliers from it
everywhere; drop `species_decay` as a stored field or make it explicitly
derived-only (documented as "do not set directly"). One source of truth.

## R1.4 Prove the two flags are independent

The spec requires `volatility_confidence` (confidence side) to work with
`resolution=False` (decay side). The eval turns both on together, so independence
is untested. Add a test: with `volatility_confidence=True, resolution=False`,
confidence recency is volatility-aware and `verify` works, while decay still uses
the flat path. And the mirror: `resolution=True, volatility_confidence=False`
decays by class but confidence/verify are unchanged.

## R1.5 Decide and document: decay rate vs verify rate diverge

`decay()` uses `lambda_eff` (includes `temperature`, i.e. conflict/resolution
heat), but `needs_verify`/`half_life_days` use the class half-life only. So a
*contradicted* fact decays faster in weight but does NOT verify sooner. Decide:
either (a) keep as-is and document that verify is volatility-class-only by design,
or (b) make a high-conflict edge also raise `verify`. Recommended: (b) is more
consistent with "surface uncertainty before acting," but either is acceptable if
documented. Add a test pinning the chosen behavior.

## R1.6 Add the provenance no-downgrade test

Confirm a later `inferred` reinforcement does not flip an edge whose provenance is
already `stated` back to `inferred`. Add an explicit assertion.

## R1.7 Run it and report (do this, don't assert)

After the revisions, actually run and paste the real output:

```
pytest -q                          # must stay green: 134+ passed, 2 skipped
pytest -q tests/test_volatility.py tests/test_resolution.py
python -m fernme.eval.volatility   # multi-seed; show the new nag-rate + sweep
```

Report per the CODEX_RULES completion format: what changed, why, files changed,
the exact commands and their real output, and remaining limitations. Do NOT push;
this still ships in one commit with TESTING.md and the README badge. If any eval
number still comes out perfect (1.000/0.000), say so and treat the fixture as not
yet hard enough -- a perfect synthetic result is a red flag, not a win.

---

# Addendum R3: make it good and turn it on (approved behavior change)

Decision from Mirko: do not ship features that sit behind an off switch. The
parts that are good become the default. The parts that are not good yet are NOT
shipped on -- but we also do not leave them as dead, switched-off code pretending
to be a feature. So: prove what is good, turn that on, and clearly mark the rest
as an explicit future milestone.

This is an **approved backwards-incompatible change** -- turning new behavior on by
default changes outputs and benchmark numbers. That is expected and allowed here.
Do not refuse it on backwards-compat grounds; instead, re-measure honestly and
update the docs.

There are two pieces with different readiness. Treat them separately.

## R3.1 Tighten the conflict signal first (precondition)

The eval reported `conflict_edges_per_user ~10.5`, which is far too high -- a real
contradiction (said vegetarian, now ordering steak) is rare, not half the profile.
A noisy conflict signal is why age+conflict verify looked bad (recall jumped but
precision/nag got worse). Before judging verify, make conflict mean what it says:

- A conflict is a genuine clash in a **single-value slot** (see
  `curation.SINGLE_VALUE_SLOTS`): a new value contradicting an existing different
  value for the same slot, e.g. `employer:oldco` vs `employer:newco`,
  `diet:vegetarian` vs `likes:steak` style negation.
- Count it once per slot, not both directions; do not count multi-value slots
  (a user can like many topics -- that is not a conflict).
- Prefer clashes involving a `stated` value (the authority case curation already
  models in `_AUTH`).

Re-run and confirm `conflict_edges_per_user` drops to a small number (roughly 0-2
per user in this fixture). If it is still high, the definition is still wrong.

## R3.2 Split the verify metric by stale-type (the measurement that decides)

Right now contradicted-stale and silent-stale are averaged together, which hides
the truth. Change the eval to label each stale fact as one of:

- **contradicted-stale**: a newer/competing value exists in the same slot (there is
  a real signal to catch).
- **silent-stale**: the value just aged out, no competing value, no signal.

Report precision / recall / nag **separately** for each subset, plus overall.
Expected shape (state plainly whether the data matches): conflict-driven verify is
strong on the contradicted subset; nothing reliably catches the silent subset.

## R3.3 Ship verify scoped to what works -- on by default

Decide from R3.2's numbers, not assumption:

- **If contradiction-scoped verify is strong** (target: precision >= ~0.8 and low
  nag on the contradicted subset): make `verify` fire by default **on genuine
  contradiction**, and do NOT raise `verify` on age-alone by default. So a memory
  that simply got old fades in weight (decay still runs) but does not nag the user;
  a memory that actually conflicts raises the flag. That is an honest, usable
  feature.
- **If even clean contradiction verify is not strong**, keep verify off, say so in
  the report, and do not ship it on. Do not tune the fixture to force a pass.

Either way, age-driven (silent-staleness) verify is documented as a known
limitation, not a working feature.

## R3.4 Turn volatility-typed decay on by default

The decay side (permanent facts persist, volatile facts fade faster) tested well
and is the main win. Make it the default behavior, choosing the cleanest config
arrangement (a dedicated default-on `volatility_decay`, or flipping the existing
gate -- your call, keep it minimal and document it). Then, because this changes
outputs:

- Re-run the FULL results suite and record real numbers:
  `python -m fernme.eval.cost_variance`, `... quality`, `... drift`, `... context`,
  `... ablation`, `... pilot`.
- Update the README benchmark tables and the "Honest status" section to the new
  numbers. If anything regresses (e.g. static recall), report it; do not hide it.
- If existing tests asserted old flat-decay behavior, update them to assert the new
  intended behavior. Do NOT delete tests to make the suite pass -- adjust the
  assertions to the new, approved behavior, and add a comment saying why.

## R3.5 Run it and report

Paste real output, per CODEX_RULES:

```
python -m fernme.eval.volatility        # conflict tightened; per-subset metrics
python -m fernme.eval.cost_variance     # and quality / drift / context / ablation / pilot
pytest -q                               # full suite green
git diff --cached --check
```

Report: what changed, why, files changed, the real commands + output, and the new
README numbers. Do NOT push -- this still ships in one commit with TESTING.md and
the badge.

## Out of scope (the next milestone, not now)

Making silent-staleness good -- Option B (per-edge learned volatility) or outside
corroboration -- is the deliberate next milestone. It needs a storage migration and
carries the censoring/gaming traps already noted. Do not start it in this pass; R3
is about shipping the ready parts on by default and scoping verify to the
contradiction case that actually works.


---

# Addendum R4: tune the half-lives before flipping decay on (correct the diagnosis)

R3 turned volatility decay on by default, and the eval revealed two regressions:
drift 0.72 -> 0.597 and stale-high-confidence-wrong 0.070 -> 0.166. **Do not ship
the on-by-default flip until these are gone.** As tuned, it is a regression on the
headline drift metric, not a win.

## R4.0 Correct the recorded cause (important)

The checkpoint/README attributes the worse stale-high-confidence-wrong to
"provenance not persisted until the migration." That is wrong and was verified:

- `eval/volatility.py::_stale_high_conf_wrong` calls `compute()` on in-memory edges
  with provenance set in the fixture; it never touches the store. Persistence
  cannot affect it.
- The real cause is `confidence.py`: with `volatility_confidence` on,
  `recency = exp(-volatility_lambda(attr)*dt)`. Slow/preference classes have long
  half-lives, so `lambda` is tiny, so recency (and confidence) stay high while a
  fact ages -- including when it is stale. The same slow decay makes old tastes
  linger, which is the drift regression.

Fix the misleading comment in `confidence.py` and the README note. The lever is the
half-lives, not the migration. State this plainly in the next report.

## R4.1 Separate "keep it" from "trust it"

Retention (decay of weight -> does the fact stay in the card) and trust (confidence
recency -> how much to rely on it) are different concerns and may use different
rates. A slow fact can legitimately stay in the card (long retention half-life) yet
have its confidence fade faster so the agent does not over-trust it as it ages.
Make this split explicit: a retention half-life and a (more conservative)
confidence half-life per class, rather than one number doing both.

Evaluate this one-sided rule for the confidence term and keep it if the benchmarks
support it: volatility may only make a fact LESS confident than flat decay, never
more. Concretely, for the confidence recency only, consider
`lambda_conf = max(volatility_lambda(attr), cfg.lam)` for the slow/preference
classes (so they never get a confidence boost that outlives flat decay), while
permanent keeps its low-lambda boost (allergy/name should stay confident) and
volatile keeps its high-lambda drop. Permanent rarely goes stale, so its boost is
safe; the slow/preference middle is the dangerous part -- be conservative there.

## R4.2 Tune per-class half-lives against the existing benchmarks

The current half-lives (permanent 3650, slow 200, preference 120, habit 90,
volatile 14) are guesses. Tune them, do not assume them. `tuning.py` already exists
to fit a decay rate against the drift simulator; extend it to search per class
(at least preference and volatile, the ones that drive drift).

Targets (all measured, multi-seed, reported real):

1. drift >= the published flat-decay number (~0.72) -- no regression. Hard gate.
2. static quality not worse than flat (~0.74).
3. context not worse than flat (~0.62).
4. volatile stale forgetting retained (the R3 win: volatile stale weight stays low).
5. stale-high-confidence-wrong <= flat baseline (~0.07) -- not worse than before.
6. permanent retention held: an old permanent fact still ranks and stays confident.

If a single half-life set cannot hit both drift and stale-confidence, that is the
signal that R4.1's split (separate retention vs confidence rates) is required --
use it.

## R4.3 Re-run, update docs honestly, then flip

```
python -m fernme.eval.volatility
python -m fernme.eval.cost_variance   # and quality / drift / context / ablation / pilot
pytest -q
git diff --cached --check
```

- Update the README benchmark + honest-status numbers to the tuned results.
- Only then is "volatility decay on by default" honest. If drift still regresses,
  keep the old flat decay as the default and report that volatility decay needs the
  retention/confidence split before it can be the default -- do not ship a known
  regression to hit a deadline.
- Do NOT push. Same single commit with TESTING.md and the badge.

## R4.4 Note on the contradicted-stale 1.000s

The contradicted-stale verify precision/recall/nag of 1.0/1.0/0.0 is by
construction (verify is defined as "the older side of a contradiction" and measured
against exactly that). It confirms the wiring and that it does not nag still-true
facts -- it is NOT proof of real-world accuracy. The real quality lives in the
conflict detector. If you want a real number there, add a metric for the detector
itself: against planted ground-truth contradictions, what fraction does it catch
(recall) and what fraction of its detections are real (precision). Small
nice-to-have, not a blocker for R4.

---

# Addendum R5: do retention correctly (resolve the false trade-off, measure the real benefit)

R4 turned volatility RETENTION off because it failed the drift gate (0.698 vs
~0.72). But that conclusion is an artifact of how it was tuned, and of a missing
benchmark. R5 fixes both, so the retention decision is made on real evidence.

## R5.0 The key realization

The drift benchmark only exercises **preferences** (tastes shifting over time), and
the tuning search found preferences want a **short** half-life (best preference=14,
volatile=7). The R3/R4 regression happened because volatility retention had
lengthened the **preference** half-life to 120 days -- which is exactly what hurts
drift. Meanwhile the benefit of volatility retention is for a **different class**:
genuinely-permanent facts (allergy, name) that are stated once and rarely repeated.

So drift-cost and retention-benefit live in different volatility classes. They were
only in conflict because the half-lives were tuned as one averaged objective and
preferences got lengthened. The correct move is **class-targeted**: keep the
classes the drift benchmark exercises (preference, and volatile) at their
drift-optimal short rates, and extend the half-life ONLY for classes drift does not
test (permanent, and cautiously slow). Done this way, retention volatility should
pass the drift gate AND deliver permanent-fact retention.

## R5.1 Build a long-horizon retention benchmark (the missing axis)

None of the current benchmarks measure what retention volatility is for. Add
`eval/retention.py` (synthetic, multi-seed, labeled synthetic):

- Simulate a long horizon (e.g. 700-1000 simulated days) with sparse reinforcement.
- Permanent facts (allergy, name, birthday): stated once early, then never mentioned again.
- Slow facts (employer, city): stated, occasionally changed.
- Volatile facts (current project, traveling): churn frequently; go stale.
- Metrics (control flat vs treatment volatility retention):
  1. **permanent retention** -- is the allergy still in the card, above floor, and
     high-confidence at day ~700 with zero repeats? (flat decay should FAIL this; that is the point.)
  2. **volatile freshness** -- is a stale current-project correctly faded/dropped? (retained R3 win.)
  3. **slow correctness** -- after a change, does the new value win and the old fade?

This benchmark is what lets "permanent facts persist" be a claim instead of a hope.

## R5.2 Re-tune with drift as a hard per-class constraint, not an averaged objective

Extend `tuning.py` so the search does NOT lengthen the classes drift tests:

- Pin `preference` (and `volatile`) half-lives to their drift-optimal short values
  (the tuning already found these: preference ~14, volatile ~7). These must not
  regress drift.
- Search/extend ONLY `permanent` (long, e.g. years) and `slow` (moderate) half-lives
  against the R5.1 retention benchmark.
- Report drift AND retention side by side for the chosen set. The chosen defaults
  must satisfy BOTH: drift >= ~0.72 (unchanged, because preference stayed short) and
  permanent retention materially better than flat.

If that set exists (it should, since permanent facts are not in the drift
benchmark), turn volatility retention ON by default. If somehow drift still
regresses, keep it off and report exactly which class caused it.

## R5.3 Stop permanent facts silently dropping (do regardless of R5.2)

Right now `allergy` is not in `identity.IDENTITY_NS`, so under flat retention an
unmentioned allergy fades on the ~35-day half-life and can drop from the card --
a safety-relevant miss. Separate two ideas that are currently conflated:

- **permanent** (name, birthday, origin, nationality, lang, allergy, health): truly
  never changes -> eligible for a floor / very-long retention (sticky).
- **slow** (employer, company, city, role, position): DOES change -> must NOT be
  force-sticky, or a job change can never fade.

Add a dedicated permanent set for the sticky/very-long-retention floor, and make
sure slow facts are NOT force-floored (reconcile with the current `IDENTITY_NS`,
which today wrongly includes employer/city/role as sticky). Add tests: an
unmentioned allergy survives 700 days; a changed employer's old value still fades.
This is a behavior change -- update affected tests to the new intended behavior with
a comment, do not delete them.

## R5.4 Run, report, decide, then flip

```
python -m fernme.eval.retention        # new long-horizon benchmark
python -m fernme.eval.drift            # must stay ~0.72
python -m fernme.eval.volatility
python -m fernme.eval.quality          # and context / cost_variance / ablation / pilot
pytest -q
git diff --cached --check
```

Report drift and retention together, the final default (retention on or off) with
the evidence for it, and update README/TESTING honestly. Only claim "permanent
facts persist" if the R5.1 benchmark shows it. Do NOT push.

## R5.5 Still out of scope

Option B (per-edge LEARNED volatility) and silent-staleness detection remain the
later milestone. R5 is about making the class-based retention correct and evidenced,
not about learning volatility per edge.
