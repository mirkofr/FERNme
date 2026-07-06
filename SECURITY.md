# Security & limitations

FERNme stores **personal data** (preferences, behavior, optionally health/dating
signals via the supernode). Treat it accordingly.

## Threat model status (honest)
| Concern | v1 status |
|---|---|
| Transport auth | Optional API key (`FERNME_API_KEY` -> `X-API-Key` header). **Off by default.** |
| Tenant isolation | Enforced by `(site, user)` on every query; covered by tests. |
| Consent | Required for all reads/writes; withdrawal purges the profile. |
| Right to delete / export | Implemented (`/delete`, `/export`). |
| Cross-site sharing | Default-deny; sensitive categories opt-in only. |
| DB at rest | SQLite, **unencrypted**. Use disk encryption; keep off cloud-synced folders. |
| Prompt injection | **Not handled.** Treat any text that reaches an agent as untrusted; FERNme does not yet sanitize event payloads used downstream. |
| Rate limiting / abuse | Not implemented. |
| PII in logs | Avoid logging payloads in production. |

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
