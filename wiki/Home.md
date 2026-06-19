# FERNme Wiki

**FERNme (Fuzzy-Edged Recall Network)** is a user-owned, near-zero-LLM memory layer for AI agents. It learns each person from their behavior — *without* an LLM in the write path — keeps the prompt-facing memory token-flat as the profile grows, and lets people see, edit, and delete everything it knows. The engine is substrate-agnostic: it remembers wherever an agent acts (websites today; desktop and mobile on the roadmap).

> Built for agents that **act** for **many** people — not single-user chat memory. Today's beachhead is websites (shopping, support, booking, healthcare, tutoring, gov); the same user-owned memory is designed to extend to desktop and mobile. "Success" is whatever the goal is.

## In one breath
- **Zero-LLM writes** — memory updates are arithmetic on a graph (0 LLM calls/interaction).
- **Flat token cost** — the memory card stays ~25 tokens forever.
- **Learns from outcomes** — good results strengthen, bad results weaken.
- **Glass-box & private** — visible, editable, exportable, deletable; consent-gated.
- **User-owned supernode** — opt-in cross-site profile the user controls.

## Pages
- [[Quickstart]] — install and run in 2 minutes
- [[Architecture]] — how the pieces fit
- [[Concepts]] — the mechanisms, explained
- [[Memory Modes]] — the cost/quality dial (pure / gated / offline)
- [[API Reference]] — service methods, REST, MCP, env vars
- [[Benchmarks]] — measured results (and their honest scope)
- [[Roadmap]] — what's built, what's next
- [[FAQ]] — common questions

## Status
Research preview (`v0.1.0`, Apache-2.0). Results are on synthetic / LLM-authored data; a real-human pilot is the pending next step. Site: https://fernme.dev
