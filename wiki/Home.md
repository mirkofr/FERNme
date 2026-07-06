# FERNme

**FERNme** (_Fuzzy-Edged Recall Network_) is a user-owned personalization memory layer for AI agents: zero-LLM deterministic core, with optional low-cost human-approved enrichment. It learns each person from consented behavior, keeps the prompt-facing memory token-flat as the profile grows, and lets people see, edit, and delete what agents use.

Built for agents that act for many people, not single-user chat memory. Today's beachhead is websites; the same user-owned memory is designed to extend to desktop and mobile. Success is whatever the goal is.

## In one breath

**Zero-LLM deterministic core** - every write and recall runs with no model calls and bounded cost.

**Optional propose-only enrichment** - an agent or caller-supplied model can propose typed relations and entity links into a human review queue; nothing auto-writes memory truth.

**Flat token cost** - the memory card stays small as profiles grow.

**Typed people & relations** - opt-in entities, aliases, fields, and labeled Hebbian relations model who people are and how they connect.

**Glass-box & private** - visible, editable, exportable, deletable; consent-gated.

**User-owned supernode** - opt-in cross-site profile the user controls.

## Pages

[[Quickstart]] - install and run in 2 minutes

[[Architecture]] - how the pieces fit

[[Concepts]] - the mechanisms, explained

[[Memory Modes]] - deterministic core plus proposal enrichment

[[API Reference]] - service methods, REST, MCP, env vars

[[Benchmarks]] - measured results and honest scope

[[Roadmap]] - what's built, what's next

[[FAQ]] - common questions

## Status

Research preview (v0.4, Apache-2.0). Results are synthetic or LLM-authored unless stated otherwise; a real-human pilot and broader real-profile benchmarks are still pending. Site: https://fernme.dev/