# Architecture

FERNme is one engine with a deterministic hot path. Model work is optional, default-off, proposal-only, and outside normal write/recall.

![FERNme architecture](https://github.com/mirkofr/FERNme/raw/main/explanation%20of%20fern/IMG_7788.PNG)

_Ingestion bridge -> namespaced vocabulary -> fuzzy Hebbian graph -> memory card -> agent. The typed entity layer sits beside the graph. Optional enrichment proposes review-queue suggestions; it never writes truth directly._

## Flow

1. **Ingestion bridge** turns input into canonical tags deterministically through a per-site catalog/vocabulary.
2. **Structured extractors** retain regex-only email, phone, URL, handle, and ISO-date values as Cabinet payload data.
3. **Hebbian write** bumps fuzzy 0-9 edges; decay fades the unused. No model call.
4. **Entity tables** store entities, aliases, fields, relation facts, and typed relations beside the tag graph.
5. **Proposal enrichment** can enqueue relation/entity-link suggestions from an agent or caller-supplied model when enabled. Human accept/reject is the only truth write trigger.
6. **Spreading activation** retrieves the relevant slice; opt-in alias aggregation can lift fragmented entity aliases together.
7. The **memory card** is the compact prompt-facing view.
8. The **Cabinet** keeps the raw event log for specific-fact recall.
9. **Outcomes** feed back to strengthen/weaken what worked.

## Modules (`fernme/`)

| Module | Role |
|---|---|
| `core/` | graph types, fuzzy 0-9 edges, event record |
| `write/` | event-to-attr mapping, Hebbian update, decay |
| `retrieve/` | spreading activation, card compile, `entity_card.py` |
| `capture/` | adapters and `extractors.py` structured-field capture |
| `store/` | SQLite/Postgres stores, including entity tables |
| `relations.py` | typed entity/relation vocabulary and validation |
| `enrichment.py` | validation for propose-only enrichment payloads |
| `curation_queue.py` | persistent human review queue |
| `service.py` | consent-gated API tying it together |
| `api/` | REST, MCP, glass-box UI |