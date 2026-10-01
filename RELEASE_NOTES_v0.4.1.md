# FERNme v0.4.1 - Pinned settings, embedding on Postgres, cloud agents

This release makes FERNme easy to embed in a server application and adds pinned
settings: explicit choices an agent and an app should always follow. It also
ships the unreleased 0.4.0b5 work (see CHANGELOG.md).

## Highlights

- **Pinned settings.** `set_setting(site, user, "plot.style", "box")` once, and
  every card carries `settings: plot.style=box`, whatever the context, card
  budget or population prior. One value per key, never decays, consent-gated,
  audited, exported and deleted with the user. Available in the service, MCP
  (`set_setting`, `get_settings`, `clear_setting`), REST (`/settings/*`) and the
  app's memory editor.
- **Embedding on Postgres.** `PostgresStore(dsn, schema="fernme",
  pool_size=(1, 10), auto_migrate=False)` plus `fernme-migrate` for the host's
  deploy step. Audit chain on Postgres. Per-(site, user) advisory locks, tested
  with concurrent processes on Postgres 16. Guide: `docs/embedding.md`.
- **Key and privacy controls.** `secret_key=` / `FERNME_AUDIT_KEY`, strict mode,
  per-site switches for the population prior and cold start, and k-anonymous
  rarity weighting on the card.
- **Hosted guidance.** SECURITY.md explains how to run FERNme for many users:
  embed the service, take the user from your own sign-in, never expose FERNme's
  REST or MCP tools directly.
- **Cloud agents** (from the 0.4.0b5 work): `fernme-mcp --transport http` with
  per-agent tokens, profile lock and owner-approved consent.

## Compatibility

- No breaking API change. `PostgresStore(dsn)`, SQLite behaviour and all defaults
  are unchanged; new arguments are keyword-only.
- Postgres databases are upgraded automatically on startup (new tables `audit`,
  `settings`, `site_policy`, `fernme_schema_version`; `fernme_secret` is now
  created by migrations). With `auto_migrate=False`, run `fernme-migrate` first.
- A custom store without `append_audit` / `read_audit` keeps working but now logs
  a `RuntimeWarning` that nothing is audited (`audit=False` silences it; strict
  mode refuses such a store).
- Behaviour change (privacy): card ranking ignores population-prior counts below
  `prior_k_anon` (5). On sites with a prior, attributes that 1-4 other users share
  can rank slightly differently. `Config(prior_rank_k_anon=False)` restores the
  old ranking. The synthetic harness output is identical.
- Postgres migrations run once per schema version. After that a restart runs no
  DDL and takes no table locks; an upgrade waits at most 30 s for table locks
  (`PostgresStore.MIGRATION_LOCK_TIMEOUT`) and can simply be retried.
- With `schema=`, the `search_path` is that schema only, so FERNme never reads or
  writes same-named tables in `public`.
- Older SQLite databases that still sign their audit chain with the legacy public
  key now log a `RuntimeWarning` at startup (they keep verifying as before).
- The core MCP tool list grows from 17 to 20 tools (about 3,200
  tool-description tokens, chars/4 estimate).
- `pip install "fernme[postgres]"` now also installs `psycopg-pool`.
