# Security & limitations

FERNme stores **personal data** (preferences, behavior, optionally health/dating
signals via the supernode). Treat it accordingly.

## Threat model status (honest)
| Concern | v1 status |
|---|---|
| Transport auth | Optional API key (`FERNME_API_KEY` -> `X-API-Key` header, compared in constant time). Without a key the REST server answers only requests addressed to `localhost`/`127.0.0.1`/`[::1]` (DNS-rebinding guard; widen with `FERNME_ALLOWED_HOSTS`). |
| Browser access (CORS) | Only local origins by default; list others in `FERNME_CORS_ORIGINS`. The bundled UI is same-origin and needs none. |
| Audit chain | HMAC hash chain on SQLite and Postgres (same format; `verify_audit` works on both). A store without an audit log runs unaudited with a warning (refused in strict mode; `audit=False` opts out). |
| Audit chain key | Per-install secret: `FernService(secret_key=...)`, else `FERNME_SECRET_KEY` (alias `FERNME_AUDIT_KEY`), else a `<db>.key` file next to a SQLite DB (0600; keep it with the DB and out of backups you share), else one secret stored per Postgres database. Older SQLite DBs keep verifying with the legacy public key, report `legacy_key: True`, and warn at startup; strict mode (`strict=True` / `FERNME_STRICT=1`) refuses the legacy key and keys that would not survive a restart. |
| Population prior | Newcomer cold start uses only the private release: attributes held by fewer than `prior_k_anon` (5) users are never seeded, sensitive attributes are never seeded, means carry Laplace noise keyed by the install secret. Card ranking (rarity weighting) treats counts below `prior_k_anon` as zero, so it never depends on how many (fewer than k) others share a trait. Per site, `set_site_policy(site, cold_start=False)` stops seeding and `prior=False` keeps no prior at all (global defaults: `Config.cold_start`, `Config.prior_enabled`). Deleting a user, withdrawing consent, or `forget_everywhere` recomputes the prior. |
| Tenant isolation | Enforced by `(site, user)` on every query; covered by tests. |
| Consent | Required for all reads/writes; withdrawal purges the profile. |
| Right to delete / export | Implemented (`/delete`, `/export`). |
| Cross-site sharing | Default-deny; sensitive categories opt-in only. |
| DB at rest | SQLite or Postgres, **unencrypted** by FERNme. Use disk/volume encryption; keep SQLite files off cloud-synced folders. |
| Pinned settings | Always on the card, so values are restricted to short plain data (8 words, 120 chars, limited charset), Unicode-normalized with invisible/bidi characters removed, instruction phrases and links rejected, and quoted on the card. Treat them as user preferences (data), never instructions. |
| Prompt injection | Tags, edited memory names, and glosses are sanitized (instruction-like text dropped, including `_`/`-` spellings). Free event `text` is stored as Cabinet data and returned verbatim by recall tools: treat it as untrusted. |
| Concurrent writers | Every service write is one transaction. SQLite uses `BEGIN IMMEDIATE`; Postgres takes transaction-scoped advisory locks per (site, user) and per site, so several processes or servers sharing a database do not lose updates (tested with concurrent processes on Postgres 16). |
| Rate limiting / abuse | Not implemented. |
| PII in logs | Avoid logging payloads in production. |

## Hosted, multi-user deployments

FERNme's MCP server (`fernme-mcp`) and REST API (`fernme.api.rest`) take `site`
and `user` from the caller. That is right for one person's own memory on their
own machine, and for the remote MCP mode, where each bearer token is locked to
one profile. It is **not** an authentication layer for many users:

- **Embed `FernService` in your own backend** and derive `user` from your own
  sign-in (session, OAuth token), never from request bodies, tool arguments, or
  anything a model wrote. Pick `site` on the server too.
- **Do not expose FERNme's REST API or MCP tools directly to your users or to
  their agents.** Put your own tools in front (for example `get_preferences` /
  `save_preference`) that call the service with the authenticated user.
- Keep `FERNME_CORS_ORIGINS` empty unless a browser app on another origin must
  call FERNme directly; the default allows only local origins.
- Use Postgres with `schema="fernme"`, a pool (`pool_size=` or `pool=`), and
  `auto_migrate=False` plus `fernme-migrate` in your deploy step
  (see `docs/embedding.md`).
- Set `secret_key=` (or `FERNME_SECRET_KEY`) from your secret store and turn on
  `strict=True`, so every server signs the audit chain with the same private key.
- Treat stored memory and settings values as untrusted data when you put them
  into a prompt: FERNme filters instruction-like text, but your prompt should
  still keep memory in a data section, not in system instructions.
- Consent stays per (site, user): ask your users once, record it with
  `consent(site, user, True)`, and offer export and deletion (`export`,
  `delete` / `forget_everywhere`).

## Before any real deployment
- Turn on `FERNME_API_KEY` (or front with a real auth proxy) and serve over TLS.
- Encrypt the database at rest; back it up off the synced folder.
- Add rate limiting and audit logging.
- Legal review for any regulated data (health = the almond-allergy case is health data).
- Do **not** use the supernode to infer/act on vulnerability (e.g. "lonely") — out of scope by design.

## Assoc-Graph Cross-User Boundary

Audit question: can user A's co-occurrence writes influence user B's spreading
activation on the same site?

Answer before the Phase 11 fix: YES. The assoc graph was site-shared and read
unfiltered into each user's retrieval.

Concrete leak path at audited baseline `6086341`:
- `fernme/service.py:144` loaded `self.store.load_assoc(site)` during
  `FernService.observe()`.
- `fernme/write/hebbian.py:52` strengthened attr-pair weights in that shared
  `AssocGraph`.
- `fernme/service.py:198` saved the shared graph back to the site store.
- `fernme/service.py:250` loaded `self.store.load_assoc(site)` for
  `FernService.card()` without passing the reading user.
- `fernme/retrieve/activation.py:37` called `assoc.neighbors(j)`, so any
  site-shared edge could participate in spreading activation for another user.

Fix: assoc reads for retrieval now use k-suppression. An assoc edge is visible to
another user only after at least `Config.assoc_min_users` distinct users have
reinforced that edge. The default is `2`. A user's own assoc contributions remain
visible to that user even below k, so single-user sites keep their behavior.
Setting `assoc_min_users = 1` restores the previous shared-site behavior.

Representation: stores keep the shared `assoc_edges` weight plus an additive
`users` distinct-contributor count, and a per-user `assoc_edge_users` table with
one row per `(site, user, a, b)` contribution. This satisfies both invariants:
the count gives an O(degree) shared-view gate, while the contributor row proves
whether the current user gets self-visibility below k. Deletion removes the user's
contributor rows and recomputes the counts, so edges that drop below k are hidden
again from non-contributors.

Residual limits: this prevents rare cross-user co-occurrence edges from affecting
retrieval by default. It does not make the SQLite database encrypted, and an
administrator with raw DB access can still inspect stored data. Population priors
remain a separate privacy boundary with their own k-anonymity/DP controls.

## Reporting a vulnerability
Open a private security advisory on the repo, or email the maintainer. Please do
not file public issues for security bugs.
