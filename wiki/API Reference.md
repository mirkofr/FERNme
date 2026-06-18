# API Reference

## FernService (Python)
```python
FernService(db_path=None, memory_mode="pure", store=None, catalog=None, vocabulary=None, tagger=None, enricher=None)
```
| Method | What it does |
|---|---|
| `consent(site, user, granted)` | grant/withdraw consent (required for all reads/writes) |
| `observe(site, user, type, payload, ts=0)` | record an interaction; `payload` may carry `tags`/`item_id`/`text` |
| `set_numeric(site, user, key, value)` | store a quantity (e.g. `cadence_days`) |
| `card(site, user, context=[], now=0)` | the token-minimal memory card |
| `recall(site, user, contains=..., limit=20)` | open the Cabinet (raw events) |
| `defaults(site, user)` | baked-in tool defaults / ranking bias |
| `record_outcome(site, user, success, attrs=None)` | reinforce/penalize on a goal result |
| `confidence(site, user, attr, importance=0.5)` | multi-signal confidence + gate (`act/observe/ask/ignore`) |
| `why(site, user, attr)` | evidence behind an attribute (observations, good/bad outcomes, dates) |
| `style_card(site, user)` | communication style + mood + tone guidance |
| `triggers(site, user, now)` | due-to-reorder + fading-favorite nudges |
| `edit / export / delete` | glass-box: override, export, delete |
| `prune_to_prior(site, user)` | differential storage: drop edges redundant with the prior |
| `private_prior(site, epsilon=1.0, k=5)` | k-anonymity + DP population prior |
| `link_identity / view_for_site / set_share` | user-owned supernode |
| `audit_log / verify_audit / forget_everywhere` | tamper-evident log + provable deletion |
| `autotune_decay()` | learn the decay rate from outcomes |

## REST endpoints (`uvicorn fernme.api.rest:app`)
`/health /consent /observe /numeric /card /defaults /recall /edit /export /delete /triggers /prior_refresh`
Docs at `/docs`; glass-box UI at `/ui`.

## MCP tools (`python -m fernme.api.mcp_server`)
`remember · recall_card · recall_events · edit_memory · forget_me · grant_consent`

## Environment
| Var | Meaning |
|---|---|
| `FERNME_DB` | SQLite path (default `~/.fernme/fernme.db`) |
| `FERNME_API_KEY` | if set, REST data routes require an `X-API-Key` header |
