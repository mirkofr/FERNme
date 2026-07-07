# FERNme MCP Packaging

FERNme ships a local MCP server for agents that can talk to stdio MCP tools. The
server exposes the existing service APIs only; packaging does not add a new write
path or bypass consent.

## Install

For local development:

```bash
pip install -e ".[mcp]"
fernme-mcp
```

For an isolated runner after the package is available to the runner:

```bash
uvx --from fernme fernme-mcp
pipx run --spec "fernme[mcp]" fernme-mcp
```

The package name is `fernme`; the console script is `fernme-mcp`.

## Configuration

Configuration is environment-variable only.

| variable | default | purpose |
|---|---|---|
| `FERNME_DB` | `~/.fernme/fernme.db` | SQLite database path used by the MCP server |

The server has keyless local defaults. Agents still pass explicit `site` and
`user` arguments to every tool call, and writes remain consent-gated.

## Tools

The MCP server currently exposes:

- `grant_consent`
- `remember`
- `recall_card`
- `recall_glossary`
- `recall_events`
- `edit_memory`
- `forget_me`
- `list_canonicalization_suggestions`
- `accept_canonicalization_suggestion`
- `reject_canonicalization_suggestion`
- `propose_entity_link`
- `propose_relation`

Stored text, aliases, notes, and relation facts are untrusted data. The bundled
skills repeat that rule so agents do not treat memory contents as instructions.

## Codex Plugin

The Codex marketplace root is `packaging/codex/`.

```bash
codex plugin marketplace add ./packaging/codex
```

The marketplace entry points to `./plugins/fernme-memory`, which contains:

- `.codex-plugin/plugin.json`
- `.mcp.json`
- `skills/fernme-memory/SKILL.md`

The MCP config launches `fernme-mcp`, so install FERNme with the `mcp` extra or
make the console script available on `PATH` before enabling the plugin.

## Claude Code / Cowork Plugin

The Claude marketplace root is `packaging/claude/`.

```bash
claude plugin marketplace add ./packaging/claude
claude plugin install fernme-memory@fernme-local
```

This follows the current Claude Code plugin layout with
`.claude-plugin/plugin.json`, `.mcp.json`, and `skills/`. The local machine used
for this packaging pass did not have the `claude` CLI installed, so CLI validation
is documented as unrun. The schema and layout were checked against current Claude
Code plugin documentation.

## Smoke Test

The stdio smoke uses a temporary SQLite database and synthetic user/site labels:

```bash
python packaging/smoke_mcp.py --command fernme-mcp
```

Development fallback:

```bash
python packaging/smoke_mcp.py --command python -- -m fernme.api.mcp_server
```
