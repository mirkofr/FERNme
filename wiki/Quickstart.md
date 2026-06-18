# Quickstart

## Install
```bash
pip install -e ".[dev,api]"
```
Optional extras: `api` (FastAPI server), `mcp` (MCP server), `viz` (matplotlib), `pgtest` (Postgres tests; Linux/Mac only).

## Try it
```bash
python run_demo.py          # cold-start -> learning -> glass-box edit
python supernode_demo.py    # one person, three sites, one owned profile
python -m pytest -q         # tests (Postgres test skips on Windows -> "73 passed, 1 skipped")
```

## Run the experiments
```bash
python -m fernme.eval.drift          # FERNme vs a frequency counter under preference drift
python -m fernme.eval.pilot          # simulated conversion lift
python -m fernme.eval.pareto         # cost/quality Pareto
```

## Run it live
```bash
FERNME_API_KEY=secret uvicorn fernme.api.rest:app --port 8077   # REST API (docs at /docs)
# open http://localhost:8077/ui                                  # glass-box memory editor
python -m fernme.api.mcp_server                                  # MCP server for agents
```

## Storage
Defaults to a local SQLite DB at `~/.fernme/fernme.db` (override with `$FERNME_DB`).
For production use `PostgresStore` — same interface. Keep SQLite off cloud-synced folders.

## Minimal code
```python
from fernme.service import FernService
svc = FernService()                       # SQLite, pure mode (no LLM)
svc.consent("mysite", "alice", True)
svc.observe("mysite", "alice", "purchase", {"tags": ["pref:organic", "pref:mid_range"]})
print(svc.card("mysite", "alice")["wire"])   # token-minimal memory card
```
