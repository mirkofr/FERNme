# FERNmark document adapter contract

The optional document adapter accepts only a FERNmark `fernmark.document`
schema-v1 envelope. FERNme calls FERNmark's `load_document()` or
`loads_document()` and does not parse or revalidate the envelope itself.
FERNmark `0.4.0a9` is an optional dependency, so importing FERNme and using any
non-document path does not require it.

## Field mapping

| FERNmark document field | FERNme capture event field | Use |
|---|---|---|
| `markdown` | `text` | Input to the active deterministic local rules adapter; stored as Cabinet data |
| `source_sha256` | `source_sha256` | Stable provenance, idempotency, explanation, and forgetting key |
| `source_name` | `source_name` | Bounded, control-cleaned display text only |
| `mime_type` | `mime_type` | Stored metadata and source of the sanitized `mime:<subtype>` tag |
| `extraction_quality` | `extraction_quality` | Stored metadata and source of `quality:<value>` |
| `warnings` length | `warning_count` | Counts-only quality reporting |
| `extractor` | `extractor` | Stored extraction provenance |
| `blocks` length | `block_count` | Counts-only document structure metadata |

The adapter always proposes `doc:<first-12-sha256>`, `mime:<subtype>`, and
`quality:<value>` through the existing tag sanitizer. If the local adapter is
active, its rules mode may also propose topic tags from Markdown. The agent
byproduct adapter never reads document text, so an embedded `FERN_TAGS:` string
cannot mint tags. No adapter output bypasses `CapturePipeline` or
`FernService.observe()`.

## Provenance and consent

`source_sha256` is stored in the same event payload as every attribute mapped
from that document. The event is therefore the explainable provenance record
for its graph contribution. Import reports contain names, hashes, counts,
quality, and tags, but omit Markdown by default.

An actual `import_fernmark` call is the explicit consent action for new document
evidence in that site/user scope. A dry run validates and reports proposals but
does not alter consent or storage. The same SHA-256 is imported at most once per
site/user, so repeat imports are idempotent rather than reinforcing.

## Forget semantics

`forget_document(site, user, source_sha256)` deletes matching document events
and any review-queue payload carrying the same provenance key. Affected
non-override graph attributes are rebuilt from the remaining chronological
event evidence, which removes document-only tags while preserving unrelated
observations. User overrides are preserved. The operation appends a counts-only
`forget_document` audit entry containing the provenance key.

Association weights are shared site-level learning and are not rewritten by
selective document forgetting in this phase. Retrieval only returns attributes
owned by the user graph, so removed document-only attributes cannot surface,
but exact historical subtraction from shared association weights is a future
storage-contract improvement.
