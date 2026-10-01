# FERNme for cloud agents (OpenAI dots, xAI Grok Bot, Meta Muse)

The 2026 wave of always-on agents runs in the vendor's cloud, not on your
computer. They keep their own memory, but you cannot inspect, correct, export,
or delete it, and each vendor's memory stays inside that vendor. FERNme gives
them one memory **you** own: visible, editable, exportable, deletable, consent
first, with each agent locked to its own profile.

Cloud agents cannot start a local program, so they reach FERNme over HTTPS:

```bash
# 1. one token per agent; each agent gets its own profile (site)
fernme-mcp --add-client grok-legal --client-site grok-legal
fernme-mcp --add-client openai-dots
# (prints each token once; only a hash is stored in clients.json next to the DB)

# 2. serve the memory tools over MCP streamable HTTP
fernme-mcp --transport http --port 8765        # http://127.0.0.1:8765/mcp

# 3. make it reachable over HTTPS with a tunnel you trust, e.g.
#    cloudflared tunnel --url http://127.0.0.1:8765
#    tailscale funnel 8765
```

Then give the agent the MCP URL `https://<your-tunnel>/mcp` and the header
`Authorization: Bearer <token>`.

## What protects you

| guard | what it does |
|---|---|
| per-agent token | no token, no access (`401`); revoke with `fernme-mcp --remove-client NAME` |
| profile lock | a token only reaches its own site/user; asking for another returns an error |
| owner-approved consent | a remote agent can only *request* consent; you approve it in the FERNme app (Review queue). A request you deny stays denied. `FERNME_REMOTE_CONSENT=agent` relaxes this. |
| no access to your disk | remote agents never see tools that read files on the FERNme machine (Obsidian import, document and photo import), even with `--tools all` |
| you approve changes | remote agents can propose merges and links but only you accept them (in the app) |
| no raw text leaves by default | `export_memory` writes a file on your machine and returns only its file name |

Keep the server behind HTTPS (the tunnel terminates TLS). Anyone holding a token
can read and write that profile, so treat tokens like passwords.

## Per platform (as of 2026-09-30)

What each vendor documents changes quickly; check before relying on it.

- **xAI Grok Bot.** Supports custom MCP servers, which must be publicly reachable
  (a tunnel works). Grok keeps memory per Bot; mirror that by giving each Bot its
  own FERNme client (`--add-client grok-legal --client-site grok-legal`,
  `--add-client grok-finance ...`). Unlike Grok's built-in memory, you can see,
  correct, export and delete what FERNme holds.
- **OpenAI dots.** Dots connect to apps through OpenAI's plugin and app ecosystem
  (Apps SDK). The launch material does not document adding an arbitrary MCP server
  to a dot; if your account can add a custom MCP connector or app, use the URL and
  token above. Otherwise this path waits for OpenAI to open it.
- **Meta Muse.** Third-party integrations go through Meta's connector program,
  which is application-based; there is no documented way to plug in your own MCP
  server yet. FERNme's REST API and MCP server are ready if Meta opens connectors
  to self-hosted services.

Claude, Codex, and other local agents keep using the stdio plugin
(`fernme-memory`); every agent can share one database, and cross-agent sharing
stays default-deny through the user-owned supernode.

## Sources

- xAI Grok Bot, custom MCP servers must be publicly reachable; per-Bot memory:
  https://www.vellum.ai/blog/official-grok-bot-breakdown ,
  https://www.memorylake.ai/en/blogs/grok-bot-per-bot-memory
- OpenAI dots (plugins/apps, Apps SDK, cloud computer):
  https://openai.com/index/introducing-dots/ ,
  https://simonwillison.net/2026/Sep/29/openai-devday-2026-live-blog/
- Meta Muse (user-controlled connections, "forget", developer connectors program):
  https://about.fb.com/news/2026/09/introducing-muse-personal-ai-agent/ ,
  https://techcrunch.com/2026/09/23/everything-new-coming-to-metas-ai-agent-muse/
