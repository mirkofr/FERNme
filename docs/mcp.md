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

For GitHub marketplace installs before a PyPI release, the shipped plugin MCP
config uses:

```bash
uvx --from "fernme[mcp] @ git+https://github.com/mirkofr/FERNme@main" fernme-mcp
```

The `main` ref is a placeholder for owner setup. Pin it to a release tag or
commit before sharing the marketplace broadly. This path works only after the
repo has been pushed to GitHub and is reachable from the target machine, either
publicly or with git credentials. No PyPI publish is required for this path.

Optional later PyPI path:

```bash
uvx --from "fernme[mcp]" fernme-mcp
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

The shipped MCP config launches `uvx` from the GitHub repo with the `mcp` extra.
For local development before the repo is pushed, use the adjacent
`.mcp.local.json` shape instead, or run the smoke test from a checkout after:

```bash
pip install -e ".[mcp]"
python packaging/smoke_mcp.py --command fernme-mcp
```

## Claude Code / Cowork Plugin

For Cowork, add the GitHub repository as a marketplace after the owner pushes it:

1. Open Customize.
2. Open Plugins.
3. Select `+`.
4. Choose Add marketplace from GitHub.
5. Enter the repo URL.
6. Install `fernme-memory`.
7. Authorize the MCP server when prompted.

For Claude Code CLI, from inside Claude Code:

```text
/plugin marketplace add mirkofr/FERNme
/plugin install fernme-memory@fernme-local
```

For local development before pushing:

```bash
claude plugin marketplace add ./packaging/claude
claude plugin install fernme-memory@fernme-local
```

The repo root also contains `.claude-plugin/marketplace.json`, so Cowork and
Claude Code can discover the marketplace by GitHub repo URL. The root marketplace
points at `./packaging/claude/plugins/fernme-memory`; it does not duplicate the
plugin body.

This follows the current Claude Code plugin layout with
`.claude-plugin/plugin.json`, `.mcp.json`, and `skills/`. The local machine used
for this packaging pass did not have the `claude` CLI installed, so CLI validation
is documented as unrun. The schema and layout were checked against current Claude
Code plugin documentation.

The shipped Claude/Cowork MCP config also uses the GitHub `uvx --from` path. Pin
the `main` ref to a release tag or commit before sharing. Actual Cowork UI
installation requires the pushed, reachable repo and is not exercised in CI.

## Smoke Test

The stdio smoke uses a temporary SQLite database and synthetic user/site labels:

```bash
python packaging/smoke_mcp.py --command fernme-mcp
```

Development fallback:

```bash
python packaging/smoke_mcp.py --command python -- -m fernme.api.mcp_server
```
