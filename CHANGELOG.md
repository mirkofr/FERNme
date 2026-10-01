# Changelog

All notable changes to FERNme. Pre-1.0: anything may change (semver 0.y.z).

## [0.4.2] - 2026-10-01

### Fixed
- PyPI release. PyPI rejects packages whose dependencies point at a git URL, so
  the `fernmark` extra (FERNmark from a git commit) made every upload since
  0.4.0b3 fail (0.4.0b4 and 0.4.1 never reached PyPI). The extra is removed; install
  FERNmark directly (`pip install "fernmark @ git+https://github.com/mirkofr/FERNmark.git@23e16ea5..."`),
  as the `fernme-docs` plugin already does. A test now fails if a direct URL
  dependency comes back. Otherwise identical to 0.4.1.

## [0.4.1] - 2026-10-01

Includes everything listed below under 0.4.0b5 and earlier unreleased work
(0.4.0b5 was never tagged).

### Added: pinned settings
- `set_setting` / `get_settings` / `clear_setting` (service, MCP core tools, REST
  `/settings/set|list|clear`, and a "Pinned settings" section in the app's memory
  editor) for explicit `key=value` choices such as `plot.style=box`. One value per
  key, never decay, and every card returns all of them in a `settings` section
  (and the wire string) whatever the context, card budget or prior. Consent-gated,
  audited with a keyed reference, included in export, removed by delete,
  `forget_everywhere` and consent withdrawal. Capped at `settings_max=32` keys,
  `settings_value_max=120` characters (8 words) per value and
  `settings_card_chars=800` in total (about 200 tokens) so the card stays bounded;
  keys in `card_exclude_ns` namespaces stay off the card. Values
  are short plain data: Unicode-normalized, invisible and bidi characters removed,
  instruction phrases, links and wire separators rejected, and shown quoted on the
  card. Users without settings get exactly the same card as before.

### Added: embedding in a server app (Postgres)
- `PostgresStore(dsn, schema=..., pool=..., pool_size=..., auto_migrate=...)`:
  own schema, a dedicated or borrowed `psycopg-pool` connection pool, and
  startup without DDL. `fernme-migrate` (and `PostgresStore.migrate_database`)
  runs the idempotent migrations; `--check` exits 1 when a migration is needed.
  Migrations run once per schema version under an advisory lock (schema creation
  included) with a 30 s lock timeout; restarts on a current schema run no DDL.
  With `schema=` the `search_path` is that schema only (no fallback to `public`).
  The zero-config `PostgresStore(dsn)` behaves as before. `psycopg-pool` joins the
  `postgres` extra. Guide: `docs/embedding.md`.
- Postgres now has the audit chain (`append_audit` / `read_audit`, same HMAC
  format as SQLite), so `verify_audit` works there. A `FernService` whose store has
  no audit log now warns that nothing is audited (it used to skip silently);
  `audit=False` opts out explicitly and strict mode refuses such a store.
- Service writes take a Postgres advisory lock per (site, user) before the site
  lock; settings writes take only the user lock. `delete` and `forget_everywhere`
  now run as one locked transaction. Tested with concurrent processes on a real
  Postgres 16 (without the locks the same test loses updates and deadlocks).

### Added: key and prior controls
- `FernService(secret_key=..., strict=...)`, `FERNME_AUDIT_KEY` (alias of
  `FERNME_SECRET_KEY`), `FERNME_STRICT`. Startup warns when an older SQLite
  database still signs with the legacy public audit key; strict mode refuses it.
- Per-site population-prior policy: `set_site_policy(site, prior=..., cold_start=...)`
  (REST `/site-policy`), plus global `Config.prior_enabled` / `Config.cold_start`.
- Behaviour change (privacy): card ranking treats prior counts below
  `prior_k_anon` as zero, so a card never depends on how many (fewer than k) other
  users share a trait. `Config(prior_rank_k_anon=False)` restores the old ranking.
  Synthetic harness output is identical.
- `set_site_policy` and `prior_refresh` run under the site lock; `private_prior`
  and `prune_to_prior` respect `prior=False`.
- SECURITY.md: hosted multi-user section (embed the service, derive the user from
  your own auth, never expose FERNme's REST/MCP directly).

### Fixed
- Audit timestamps are stored as floats on every store, so an integer `ts` cannot
  break `verify_audit` after a round trip.
- `forget_everywhere` also removes managed document files, like `delete`.

### Added: cloud agents, outcome tools, memory inbox
- Remote MCP for cloud agents (OpenAI dots, xAI Grok Bot, and other clients of
  remote MCP servers): `fernme-mcp --transport http` serves the core tools over
  MCP streamable HTTP. Each agent gets its own bearer token
  (`--add-client/--list-clients/--remove-client`; only SHA-256 hashes are stored in
  `clients.json`), every token is locked to one site/user, and consent over HTTP
  defaults to owner approval. Guide: `docs/cloud-agents.md`. Works on mcp 1.x and 2.x.
- Remote agents cannot call tools that read files on the FERNme machine
  (`import_obsidian`, `import_document`, `remember_photo`) or accept their own
  canonicalization suggestions; these are not listed over HTTP and are refused if
  called. A consent request the owner denied stays denied in inbox mode, and a
  confirmed document import on an inbox server files a request instead of granting
  consent.
- MCP core tools `record_outcome`, `why`, `export_memory` (export writes a 0600 file
  with a unique name and returns only its path and counts; remote agents get only the
  file name). `record_outcome` clamps `weight` to 0..1, leaves hand-edited memories
  alone, and with no `attrs` uses the last non-outcome event. Server instructions tell any MCP client how
  to use FERNme.
- `remember` returns `near_duplicates` when a new tag looks like an existing one
  (`pref:oat_milk` vs `pref:oat-milk`, `likes:tea` vs `pref:tea`). No model call.
- Memory inbox: consent requests are stored and shown in the app's Review queue with
  Approve / Deny (`/consent-requests/list`, `/consent-requests/decide`).
  `FERNME_CONSENT_MODE=inbox` makes owner approval the only way to grant consent.

### Changed
- Single-value slots (diet, city, employer, ...): the newest confirmed value
  (stated, or seen twice) ranks ahead of older values on the card
  (`card_single_value_latest=True`). Synthetic slot-change regime: FERNme recall
  0.400 -> 0.933, stale 1.000 -> 0.111; every other regime unchanged. Slots holding
  a value written without a time (ts=0) keep plain ranking, since "newest" is unknown.
- `decay()` on a user with no memories no longer writes anything (it used to
  recreate a row for a deleted user); exports omit internal `_` bookkeeping keys.
- Event recall breaks timestamp ties by insertion order.
- `decay()` no longer overwrites `last_reinforced` (conflict detection and verify
  need the real last-seen time); a per-user decay clock keeps repeated calls safe.
- The people/entity card uses the same read-time fading as the plain card.
- Cards on large sites load only the reachable part of the association graph
  (exact same activation). Synthetic 89k-edge site: card about 178 ms -> 23 ms;
  small sites keep the single full read.
- The token counter no longer downloads tiktoken's encoding on import; it uses it
  when already cached (`FERNME_TOKENIZER_DOWNLOAD=1` allows the download) and
  otherwise estimates.
- Evaluation harness: fixtures renamed from the reserved `style:` namespace to
  `look:` (the card never shows `style:`, which had capped FERNme's recall), and a
  new `slot_change` regime. FERNme static recall 0.750 -> 0.917, abrupt drift
  0.625 -> 0.833 (stale 0.417 -> 0.208); baselines unchanged. Synthetic data.

### Changed: agent safety on MCP tools
- `grant_consent` asks first: a call without `confirm=true` stores nothing and
  returns a question the agent must show the user; only a second call with
  `confirm=true` grants consent. Withdrawing still works in one call. The REST
  `/consent` endpoint is unchanged.
- Profile lock: when `FERNME_SITE` / `FERNME_USER` are set, every MCP tool refuses
  any other site/user with a visible error, so one agent cannot read or write
  another profile. `FERNME_ALLOW_OTHER_PROFILES=true` restores the old behavior.
  Previously these variables only set defaults.
- `import_obsidian` (MCP) previews by default; pass `dry_run=false` to write. The
  CLI and service defaults are unchanged.

### Changed: documents and photos are an optional add-on
- The MCP server groups its tools: `core` (14 memory tools), `documents` (9
  FERNmark document tools) and `photos` (2). `fernme-mcp --tools ...` or
  `FERNME_MCP_TOOLS` picks the groups; the default `auto` serves core plus any
  add-on whose feature flag is on, so existing standalone setups keep their tools.
- The `fernme-memory` plugin now runs `--tools core` without FERNmark: it
  installs for anyone, and each agent session loads about 2,200 tokens of tool
  descriptions instead of about 4,300 (rough chars/4 estimate). Document and photo
  tools moved to the new optional `fernme-docs` plugin, which shares the same
  database. Plugin manifests, skills and marketplaces for Claude and Codex updated.
- Plugins pin the `v0.4.1` release tag (the owner creates it on release).

### Security and privacy (from the 2026-09-30 review)
- **Population prior leak.** A newcomer's cold-start card was seeded from the raw
  prior, so a trait only one user had (for example a health condition) appeared
  on every new user's card, and it survived `forget_everywhere` because
  `save_prior` never removed rows. Cold start now uses only the private release
  (k-anonymous with `prior_k_anon=5`, sensitive attributes excluded, Laplace noise
  keyed by the install secret); `save_prior` replaces the site's rows; `delete`,
  consent withdrawal, and `forget_everywhere` recompute the prior. Behavior
  change: sites with fewer than 5 users holding an attribute no longer seed it.
- **Lost writes under concurrency.** Parallel writers (REST thread pool, MCP + UI
  on one DB) could load a half-rewritten graph and save it back: 8 threads x 50
  writes kept 17 hits. Store writes now run in one transaction per service call
  (`store.transaction()`, `BEGIN IMMEDIATE` on SQLite; on Postgres a real
  transaction plus a per-site advisory lock, so separate server processes also
  serialize); a failure, including a failed commit, rolls back the graph,
  Cabinet event, and audit together.
- **REST exposure.** CORS allowed every origin and keyless servers answered any
  host. CORS is now local-only by default (`FERNME_CORS_ORIGINS`), keyless servers
  only answer local host names (`FERNME_ALLOWED_HOSTS`), the key check is
  constant-time, and `/runtime-defaults` needs the key when one is set.
- **Prompt injection via stored names.** `edit()` accepted free text as a memory
  name and glosses were stored verbatim; both now go through the tag and display
  sanitizers, which also catch `_`/`-` spellings such as
  `ignore_all_previous_instructions`. Behavior change: `edit()` raises
  `ValueError` (REST 400) for a *new* name that is not a valid tag; memories
  already in the graph stay editable under their existing names.
- **Obsidian import** no longer follows symlinks out of the vault.
- **Audit chain** was keyed with a constant published in the source. New
  databases get a per-install secret (`fernme/install_key.py`: `FERNME_SECRET_KEY`,
  else a `<db>.key` file created atomically next to a SQLite DB, else one secret
  stored per Postgres database); existing databases keep verifying with the legacy
  key and say so. Edit entries store a reference keyed by that secret instead of
  the memory name. Keep the `.key` file with its database.
- **Differential privacy seed** defaulted to 0, so the noise could be recomputed;
  `private_prior()` now derives it from the install secret unless a seed is passed.
- **Supernode:** sharing an ordinary category (`topic`) no longer carries
  sensitive members (`topic:mental_health_*`) along; that needs an explicit
  `sensitive:<category>` rule. Deleting a user also removes their identity links
  and, when no linked site remains, their sharing rules.

### Performance
- Writes no longer rewrite the user's whole history or load the site's whole
  association graph: only changed edges, new history rows, and the touched
  attribute pairs are read and written.
- `history_cap=64` timestamps per attribute (first + most recent), with a
  closed-form estimate for the dropped hits in base-level activation (Petrov
  2006). Synthetic check: |error| < 0.02 in log activation; harness results
  unchanged. Single-user write latency (synthetic, one machine): about 6 ms at
  10k stored events, previously about 18 ms at 1k and over 280 ms at 10k.

### Changed
- `card_read_decay=True`: the card applies decay on the user's own activity clock
  and moves memories that have faded below `floor` behind current ones, even if
  no `decay()` job runs. On the 300-message synthetic race the card drops the
  pre-drift `topic:python` / `food:croissant` and shows `pref:mint-tea`; the
  unified harness is unchanged in every quality cell (tokens within 0.4). A card
  requested with `now=0` (the MCP default) is not decayed, and memories written
  with `ts=0` are not aged against wall-clock writes. Set `card_read_decay=False`
  for the previous behavior.

### Fixed
- `tests/test_postgres.py::test_canonicalization_suggestions_on_postgres` used an
  alias pair below the suggestion threshold and failed on main whenever Postgres
  tests ran; it now uses a namespace duplicate like the SQLite test.
- `fernme-mcp` failed on any fresh install because `mcp>=1.0` resolved to the
  2.x SDK, which renamed `mcp.server.fastmcp.FastMCP` to
  `mcp.server.mcpserver.MCPServer`; the server then exited with the misleading
  "Install the 'mcp' package". The server now loads on both SDK majors
  (dependency range `mcp>=1.0,<3`) and reports the installed version when an
  SDK is present but unusable.
- The bundled Claude/Codex plugin configs add `--with "mcp>=1.0,<2"` so the
  already-tagged `v0.4.0b4` build (1.x-only) resolves a compatible SDK.

### Added
- `python -m fernme.eval.cost_race`: deterministic synthetic token race over one
  fictional user (FERNme card vs full history). `--with-mem0-prompts` also runs
  the real Mem0 OSS pipeline with a stand-in model (no API calls) and counts the
  tokens of Mem0's own extraction prompts; `--html` fills `demo/token_race.template.html`.
- `python -m fernme.eval.mem0_h2h`: owner-run recall head-to-head against real
  Mem0 on the unified harness scenarios, with an offline `--check` preflight and
  a key-less `--backend stub` plumbing mode. See `docs/mem0-head-to-head.md`.

### Changed
- README front page cut to one pitch, three reproducible claims, and a 60-second
  quickstart; the long feature list moved to `docs/features.md`. Test counts now
  match a real run, the quickstart no longer needs a local FERNmark wheel, and the
  Mem0 write cost cites the measured 1 call per message (Mem0 OSS 2.2.1).
- Eval module docstrings use `python -m fernme.eval.*` instead of the old
  `fern.eval.*` module path.

## [0.4.0b2] - entity layer, local UI, and document import

### Added
- Added a default-off managed FERNmark document workflow for raw supported files
  and existing envelopes. A redacted preview performs no writes; confirmation
  atomically stores UTF-8 Markdown plus a canonical envelope under a safe,
  owner-scoped vault path and records a durable document catalog row.
- Added additive SQLite/PostgreSQL `documents` and `document_tags` tables with
  owner isolation, approved-tag provenance, archive/supersede/pin/authority
  lifecycle state, selective forgetting, and idempotent schema setup.
- Added bounded `recall_documents` metadata retrieval with continuation and an
  explicit graph document-evidence overlay. The overlay is off by default,
  contains typed provenance links, and does not change `recall_card` or lower
  `assoc_floor`.
- Added human-reviewed document tag proposals linked to stable document IDs.
  The bundled skills treat generated Markdown as untrusted data, infer at most
  eight tags only as a byproduct of the current agent turn, and never auto-accept.
- Pinned the FERNmark optional dependency and bundled MCP plugin configuration
  to immutable commit `23e16ea5b01f4ce77fee81b5bf4f7e0d87d77bae` while keeping
  the FERNme package version at `0.4.0b2`.
- Fixed (Phase 18): the managed `import_document` path wrote events with
  `attrs=[]` and always reported `tags_written=0`, so native document tags
  never reached the graph. Confirmed imports now flow through the same
  `CapturePipeline` + document adapter + `service.observe()` path as
  `import_fernmark`, so there is one import write path, not a parallel one.
  Extended the Level-1 native tag set (still zero-LLM, still sanitized through
  the existing tag path) with source origin (raw vs. envelope), managed-vault
  and catalog-status identity, a safe title when FERNmark classifies one, and
  explicit task/use tags from the calling workflow.
- Fixed a managed-vault path-traversal guard that could silently swallow a
  hostile relative pointer (and skip deletion without raising) whenever the
  pointer's intermediate directories did not happen to exist on disk; the
  containment check is now purely lexical and always enforced first.
- Added `remember_document_use` to record that a document was used for
  something as a byproduct of work already done in the turn (never a reason
  for a separate model call); it writes one normal event linking a
  `task:<purpose-slug>` tag to the document's own `doc:` tag.
- Added `read_document` for bounded, paged, audit-logged access to a
  consented document's stored canonical Markdown by document reference only
  (never a filesystem path), with a server-enforced `max_chars` cap.
- Added `backfill_documents` (service method, `python -m
  fernme.backfill_documents` CLI, and MCP tool) to create catalog rows for
  document evidence imported before the managed catalog existed, without
  duplicating events or rewriting graph edges. Dry-run by default, idempotent,
  consent-respecting, and audit-logged.
- `recall_documents` now returns a `hint` field naming `import_document` when
  the catalog has nothing to show.
- Added an optional FERNmark `0.4.0a9` document adapter and consent-action CLI.
  Schema-v1 envelopes are validated only by FERNmark, then mapped into the
  existing zero-LLM capture and `observe()` path with per-document SHA-256
  provenance, idempotent same-hash imports, redacted reports, and selective
  document forgetting for events, graph evidence, and review suggestions.
- Added `import_document` and `forget_document` MCP tools with a mandatory
  no-write preview before user-confirmed import, redacted metadata-only output,
  explicit local-path validation, and clean optional-extra errors.
- Added default-off image memory with local pointer storage, verified EXIF/GPS
  removal, bounded thumbnails, owner-scoped deduplication, `asset:<uuid>` graph
  links, sensitive-media supernode exclusion, and cascading file deletion.
- Added two-step `remember_photo` and user-favoring `forget_photo` MCP tools.
  Photo tags ride perception the calling agent already performed, so FERNme
  makes 0 extra model calls on write. The optional `media` extra provides Pillow.
- Persisted edge provenance (`stated`/`inferred`) in SQLite and Postgres stores,
  including migration defaults and consolidation snapshot/undo preservation.
- Added deterministic structured-field extraction at capture ingest for email,
  phone, URL, handle, and ISO-date payload retention.
- Added the typed entity layer: additive SQLite/Postgres tables and deterministic
  service APIs for entities, aliases, fields, and Hebbian typed relations.
- Rejected reversed relation surfaces such as `buys_from` instead of storing
  direction-inverted canonical relations.
- Added opt-in entity-aware retrieval integration: alias activation aggregation,
  compact card enrichment, card token estimates, and one-hop stated relation pull.
- Added entity-aware graph/map rendering: canonical entity nodes with alias
  grouping, labeled typed-relation edges, and a synthetic Elena entity map demo.
- Added fictional entity-layer acceptance fixtures covering commerce and
  non-commerce research/family scenarios.
- Added `python -m fernme.eval.entities`, a reproducible synthetic micro-eval for
  the A2 alias-fragmentation dilution effect with entity aggregation off vs. on.
- Added `python -m fernme.eval.harness`, a synthetic hidden-answer-key eval gate
  covering static, abrupt drift, gradual drift, staleness, contextual,
  fragmented-entity, and outcome regimes across FERNme, entity flags, recency,
  frequency, and pure-Python BM25 Cabinet baselines.
- Reconciled README benchmark claims to the unified harness as the public source
  of truth, including the measured trade-offs, flat token cost, zero-model-call deterministic core,
  entity aggregation, and FERNme-only outcome feedback loop.
- Added relation facts for typed entity relations in SQLite/Postgres, with
  deduplicated inert notes, explicit fact deletion, and entity-forget cascade.
- Added memory map v2 entity-kind rendering for the Elena demo: owner/person/org/
  project colors, pink info markers, typed relation edges with relation-fact
  badges, and edge inspection with most-recent facts first.
- Added suggest-and-approve canonicalization: deterministic alias-merge and
  entity-link suggestions, persistent per-user review queues in SQLite/Postgres,
  REST/MCP adapters, and the synthetic `python -m fernme.eval.canonicalization`
  precision/recall report. Nothing auto-applies to memory truth.
- Added default-on cross-user assoc k-suppression (`assoc_min_users=2`) so rare
  one-user co-occurrence edges stay self-visible but do not influence other users'
  retrieval on shared sites until enough distinct users reinforce them.
- Added default-off propose-only enrichment: agent/MCP relation and entity-link
  proposals plus optional caller-supplied batch `enrich(llm_fn=...)` enqueue
  suggestions for human approval; deterministic write/recall stays zero-model-call.
- Documented first real-profile validation (n=1, maintainer's own 722-tag profile):
  entity flags improved a fragmented person's card rank 11→6, surfaced a
  previously missed `contact_of` relationship, and kept token cost flat.
- Added MCP packaging: `fernme-mcp` console script, bundled Codex and Claude
  Code/Cowork plugin manifests, a standing memory skill, docs, and stdio smoke
  coverage using a temporary synthetic SQLite database.
- Made the Claude/Cowork plugin GitHub-marketplace installable without PyPI by
  adding a repo-root marketplace and switching shipped MCP configs to `uvx`
  from the Git repo with the `mcp` extra.
- Pinned shipped plugin MCP configs to the reproducible test release
  `0.4.0-beta.1` and aligned the package/plugin versions for external testers.
- Added deterministic Obsidian vault import via service, CLI, and MCP: note text
  is stored as Cabinet data, frontmatter tags use the existing vocabulary, and
  wikilinks/aliases queue human-reviewed suggestions only.
- Made installs self-configuring for `0.4.0b1`: the default package includes MCP,
  all entry points share `~/.fernme/fernme.db` unless `FERNME_DB` overrides it,
  `fernme-mcp --print-db-path` exposes the path, and plugin configs pin
  `v0.4.0b1`.

## [0.3.0] — curation, capture adapters, and per-memory meaning

### Added
- **Curation / editing policy** (`fernme/curation.py`, off by default) — deterministic
  conflict detection (polarity, same-slot value change, declared semantic mutex),
  an authority axis (an *inferred* signal never silently overrides an *explicit*
  statement), supersession recorded as a tombstone event, and a 0-token clarifying
  question surfaced from `observe()` instead of a silent overwrite.
- **Pluggable capture adapters** (`fernme/capture/`) — `agent` (host LLM emits tags
  as a byproduct, ~20-40 tok), `signal` (structured events to tags, 0 tokens), and
  `local` (rules now, Ollama/Hermes later, 0 API tokens). Installer prints the
  per-method token cost; `AGENTS.md` documents wiring Claude/Codex/Hermes.
- **Per-memory meaning** (`fernme/glossary.py`) — `context` (the sentence a memory
  came from, stored free) and `gloss` (supplied by the tagger or a deterministic
  namespace template, 0 tokens). `service.glossary()` assembles `{tag: {gloss,
  context}}`; MCP gains `remember(glosses=...)` and `recall_glossary`.

### Notes
- All additive and off/transparent by default; prior behaviour and benchmarks
  unchanged. 119 tests passing.

## [0.2.1] — recall latency fix

### Fixed
- **Recall is no longer O(all association edges).** `AssocGraph.neighbors()` scanned
  every association edge on every node, every hop — O(nodes × edges × hops) — pushing
  recall past 200ms at a few hundred memories. Added an adjacency index (`_adj`, built
  lazily and kept in sync by `set_edge()`), making `neighbors()` O(degree). Measured
  p95 dropped from ~222ms to ~2ms at 200 memories, and stays ~30ms at 1,000 memories
  over a 50k-edge graph. No API or behavior change; pure performance.

### Added
- `tests/test_perf_recall.py` — index-correctness + a latency-ceiling regression guard.
- `docs/v0.3_scaling.md` — the measurements and the bounded-working-set plan for the
  remaining single-large-graph case.

## [0.2.0] — salience, categories, memory map

### Added
- **Salience-modulated forgetting** — optional per-edge `salience` (off by default,
  `salience_beta=0`) so behaviorally significant memories (strong outcomes, dislikes,
  rating extremity) decay slower. Decoupled from confidence: retain vs. act.
- **Deterministic memory categories** (`fernme/categories.py`) — a reproducible,
  no-LLM `namespace -> category` rollup; `graph()` now emits a `category` per node and
  the category list.
- **`/why` REST endpoint** — exposes the existing explainability evidence over HTTP.
- **Interactive memory-map demo** (`demo/elena/`) — category bubbles, associations,
  Elena at the center, click-to-inspect a memory.
- Natural-data **Elena evaluation** + LoCoMo-style QA, paper (Markdown + LaTeX),
  related-work comparison.

### Fixed
- **DB forward-compatibility:** auto-migrate `user_edges` to add `fast`/`salience`
  columns on open (previously, DBs created before these columns failed on write).

### Notes
- Salience and categories are additive and off/transparent by default; existing
  behaviour and all prior numbers are unchanged.

## [0.1.0] — first public release
Initial open-source release. A per-site, user-owned Hebbian preference-graph memory
for transactional agents. Highlights:

- **Historical core framing** — saturating Hebbian writes, spreading-activation
  retrieval, ACT-R decay, token-minimal flat memory card.
- **Ingestion bridge** — per-site catalog + controlled namespaced vocabulary (no tag drift).
- **Cost/quality dial** — `memory_mode` pure / gated / offline.
- **Outcome learning** (any goal), **communication-style & mood** memory, **explainable
  provenance** (`why`), **multi-signal confidence** + ask-budget gate, **self-tuning
  forgetting**, **multi-timescale** memory.
- **User-owned & private** — consent-gated, glass-box editable, k-anonymity + differential-
  privacy collective priors, tamper-evident audit chain, provable right-to-be-forgotten,
  user-owned cross-site supernode.
- **Deployable** — SQLite or Postgres (tested vs. real PG 16), REST + MCP servers, glass-box UI.
- 77 tests passing. Apache-2.0.

> Research preview: results are on synthetic / LLM-authored data; a real-human pilot and the
> Mem0 head-to-head are the pending next steps. (Built through several internal iterations
> before this first public cut.)
