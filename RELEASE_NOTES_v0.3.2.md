# FERNme v0.3.2 — resolution/temperature decay (opt-in), richer categories, honest status

A small, additive release. The headline is an **opt-in** memory-lifecycle layer that
makes decay depend on how well-resolved a memory is, plus a wider category map for the
glass-box view. Everything new is **off by default**, so prior behaviour and all
benchmarks are unchanged. **Full suite green: 119 passed, 2 skipped.**

## 🆕 Resolution / temperature decay (off by default)

A new pure module, `fernme/resolution.py`, lets a memory's effective decay rate depend
on its **resolution** (how well-evidenced it is) and **temperature** (uncertainty plus
conflict heat), instead of one flat rate. UOR-inspired, but translated into FERNme's own
primitives, no external dependency.

- New `Config` knobs, all defaulting to no-op: `resolution=False` (master switch),
  evidence-slot weights, `heat_gain`, `resolution_cap_non_override=0.95`,
  `temperature_floor_non_override=0.05`, `species_decay`, `phase_crystal`.
- `decay()` uses `resolution.lambda_eff(...)` only when `resolution=True`; otherwise the
  decay path is byte-for-byte unchanged.
- Conflict "heating" accelerates forgetting when enabled: the service builds a conflict
  map from negative counterparts (`!attr`) and, when `curation=True`, from curation's
  same-slot / semantic checks.
- **Guardrail:** only an explicit user lock (`source="override"`) can ever reach zero
  decay. Non-override memories keep a temperature floor, so nothing becomes permanent by
  accident.

**Honest scope:** this layer is implemented and **unit-tested**, but its *efficacy*
(versus the current flat decay) is **not yet validated**. It is not part of the results
suite, and there is no quality claim until a control-vs-treatment harness is run on the
fixtures. Leave `resolution=False` for production until then.

## 🗂 Richer categories for the glass-box view

`categories.py` adds two categories — **Knowledge & ideas** and **Milestones & events** —
and remaps namespaces accordingly: `topic`, `tech`, `concept`, `fact`, `lesson`,
`insight`, `comparison` now group under *knowledge*; `milestone`, `event`, `decision`
under *milestones*; `email` and `github` under *facts*; `tool` under *habits*. This only
affects how memories are grouped/coloured in the map and category API, not stored data.

## 📝 Honest-status correction in the README

The README's "Honest status" no longer lists resolution decay among the validated
features. It is now called out separately as new, opt-in, unit-tested, and pending
efficacy validation, consistent with the project's rule that every claim is backed by a
test or a reproducible experiment.

## Compatibility

Additive and backwards-compatible. No schema change. With `resolution=False` (the
default) the engine behaves exactly as v0.3.0. The decay-rate path is unchanged unless
the flag is set.
