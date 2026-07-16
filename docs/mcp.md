# FERNme MCP Packaging

FERNme ships a local MCP server for agents that can talk to stdio MCP tools. The
server exposes the existing service APIs only; packaging does not add a new write
path or bypass consent.

## Install

For normal installs:

```bash
pip install fernme
fernme-mcp --print-db-path
fernme-mcp
```

The default install includes the MCP server and creates its SQLite database at
`~/.fernme/fernme.db` on first use. `fernme-mcp --print-db-path` prints the
resolved path to stdout and exits without starting the server. Normal startup
logs the same path to stderr so stdout stays reserved for MCP JSON-RPC.

To make Codex, Cowork, CLI import, and the graph UI share one memory, set the
same `FERNME_DB` path in each environment. `FERNME_SITE` and `FERNME_USER`
provide optional local defaults for tools or CLIs that omit explicit values.

For local development from a checkout:

```bash
pip install -e ".[dev,ui]"
fernme-mcp
```

For GitHub marketplace installs before or alongside PyPI, the shipped plugin MCP
config uses:

```bash
uvx --from "fernme[mcp] @ git+https://github.com/mirkofr/FERNme@v0.4.0b1" fernme-mcp
```

The shipped plugin is pinned to the reproducible release ref `v0.4.0b1`, so
testers fetch the same server build. The git tag `v0.4.0b1` maps to the package
version `0.4.0b1` in PEP 440 form. The owner pushes this tag; Codex does not tag
or publish.

This path works only after the owner has pushed `main` and created plus pushed
the `v0.4.0b1` tag to GitHub, and the repo is reachable from the target machine,
either publicly or with git credentials. No PyPI publish is required for this
path.

Optional graph UI install:

```bash
pip install "fernme[ui]"
fernme-ui --db "/path/to/fernme.db"
```

The package name is `fernme`; the console scripts are `fernme-mcp` for MCP and
`fernme-ui` for the local REST/graph UI. `fernme-ui` starts the local server,
opens `/graph` by default, and accepts `--db`, `--site`, `--user`, `--host`,
`--port`, and `--no-open`. If `--site` and `--user` are omitted, the graph UI
uses environment defaults or the single granted consent context in the DB.

## Configuration

Configuration is environment-variable only.

| variable | default | purpose |
|---|---|---|
| `FERNME_DB` | `~/.fernme/fernme.db` | SQLite database path used by the MCP server |
| `FERNME_SITE` | `default` | Optional local default site for tools that omit `site` |
| `FERNME_USER` | `local` | Optional local default user for tools that omit `user` |

The server has keyless local defaults. Agents still pass explicit `site` and
`user` arguments to every tool call, and writes remain consent-gated.

## Tools

The MCP server currently exposes:

- `grant_consent`
- `remember`
- `recall_card`
- `recall_glossary`
- `recall_events`
- `import_obsidian`
- `edit_memory`
- `forget_me`
- `list_canonicalization_suggestions`
- `accept_canonicalization_suggestion`
- `reject_canonicalization_suggestion`
- `propose_tags`
- `propose_entity_link`
- `propose_relation`

Stored text, aliases, notes, and relation facts are untrusted data. The bundled
skills repeat that rule so agents do not treat memory contents as instructions.

## Obsidian Vault Import

The service and MCP server expose a deterministic Obsidian import path for local
vaults:

```bash
python -m fernme.import_obsidian ./vault --site demo --user elena --dry-run
python -m fernme.import_obsidian ./vault --site demo --user elena --max-notes 100
```

Agents can call `import_obsidian(site, user, path, dry_run, include, exclude,
max_notes)` through MCP. The `path` is resolved on the MCP server machine, not
the chat client. The tool is consent-gated and returns a redacted counts-only
summary; it does not echo note contents.

The importer preserves Markdown bodies in the Cabinet as data, maps simple YAML
frontmatter tags through the existing vocabulary, stores structural importer
metadata only in event payloads, runs structured extractors on each note, and
queues wikilink or alias candidates in the human review queue. It never
auto-applies entity links or alias truth.

If the imported notes have no explicit tags, the import still succeeds but the
graph can remain empty. Agents should then recall a small batch of imported
Cabinet events and use `propose_tags` to queue concise namespaced tags inferred
from the prose for human review. Accepted tag proposals write through the normal
`observe()` path and become active graph memory; rejected proposals never touch
memory truth.

## Codex Plugin

The Codex marketplace root is `packaging/codex/`.

```bash
codex plugin marketplace add ./packaging/codex
```

The marketplace entry points to `./plugins/fernme-memory`, which contains:

- `.codex-plugin/plugin.json`
- `.mcp.json`
- `skills/fernme-memory/SKILL.md`

The shipped MCP config launches `uvx` from the pinned GitHub tag with the `mcp` extra.
It includes an empty `FERNME_DB` env slot that users can fill with the path from
`fernme-mcp --print-db-path` when they want the plugin to use a specific DB.
For local development before the repo is pushed, use the adjacent
`.mcp.local.json` shape instead, or run the smoke test from a checkout after:

```bash
pip install -e ".[dev,ui]"
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

The shipped Claude/Cowork MCP config also uses the GitHub `uvx --from` path,
pinned to `v0.4.0b1`. Actual Cowork UI installation requires the pushed,
reachable repo and the pushed tag, and is not exercised in CI.

## Smoke Test

The stdio smoke uses a temporary SQLite database and synthetic user/site labels:

```bash
python packaging/smoke_mcp.py --command fernme-mcp
```

Development fallback:

```bash
python packaging/smoke_mcp.py --command python -- -m fernme.api.mcp_server
```
