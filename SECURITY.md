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

## Reporting a vulnerability
Open a private security advisory on the repo, or email the maintainer. Please do
not file public issues for security bugs.
