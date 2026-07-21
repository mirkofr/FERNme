# Managed FERNmark document evidence

FERNme supports two document paths:

- The backward-compatible envelope adapter accepts validated
  `.fernmark.json` files through `FernService.import_fernmark()`.
- The managed workflow accepts raw FERNmark-supported files or existing
  envelopes through `import_document`. It is additive, default-off in the
  engine, and enabled by the bundled plugin.

FERNmark remains the conversion and envelope-validation boundary. FERNme uses
its public `convert()`, `load_document()`, and `dumps_document()` APIs. The
packaged dependency is pinned to immutable Git commit
`23e16ea5b01f4ce77fee81b5bf4f7e0d87d77bae`, which reports version `0.4.0a9`.

## Three separate layers

The ordinary hot memory graph is unchanged. It still uses normal Hebbian
writes, confidence, decay, spreading activation, and compact-card limits.
Documents are not made durable by changing graph weights.

The durable catalog stores source identity, safe vault-relative pointers,
quality metadata, lifecycle state, explicit pin/authority flags, and approved
tag provenance. Catalog rows and document-tag mappings do not decay.

The document graph overlay is requested explicitly. It materializes a bounded
set of document hubs and typed `tagged_with` / `supported_by` provenance links.
It does not lower `assoc_floor`, create a tag clique, or change `recall_card`.

## Preview and confirmation

`import_document(..., confirm=false)` converts or validates the explicit local
source in memory. It returns a safe source name, SHA-256 prefix, MIME type,
quality/count metadata, deterministic provenance tags, and planned relative
filenames. It creates no consent, files, events, catalog rows, suggestions, or
temporary-file residue.

After approval, `confirm=true` writes UTF-8 Markdown and a canonical envelope,
stores the complete Markdown as Cabinet evidence, and creates one catalog row.
The report returns the stable document ID, full SHA-256, and vault-relative
pointers. It never returns document bodies or absolute paths.

Confirmed import does not silently write semantic document tags. The bundled
skill reads only the selected generated Markdown as untrusted data, proposes at
most eight topical namespaced tags as a byproduct of the current agent turn,
links the proposal to the document, and tells the user review is pending.
Accepted tags flow through normal `observe()` behavior and also create durable
document-to-tag mappings.

## One write path, extended Level-1 native tags

Every confirmed import -- legacy `import_fernmark` and the managed
`import_document` alike -- writes through the same
`CapturePipeline.ingest()` -> `service.observe()` call. There is exactly one
place that turns adapter proposals into stored graph evidence; the managed
workflow layers vault storage and catalog bookkeeping on top of that one
write, it does not fork a second one. `tags_written` in the import report
always reflects the attrs actually stored on the event, not just proposed.

The managed workflow's `ManagedDocumentAdapter` extends the legacy
`DocumentAdapter`'s three tags (`doc:<sha12>`, `mime:<subtype>`,
`quality:<value>`) with more deterministic, zero-LLM Level-1 facts, all run
through the same tag sanitizer:

- `origin:raw` or `origin:envelope` -- whether the source was converted from a
  raw file or was already a FERNmark envelope.
- `vault:managed` -- this event belongs to a vault-managed catalog document.
- `docstatus:<status>` -- the catalog lifecycle status at import time.
- `title:<slug>` -- only when FERNmark classified a block as `kind="title"`
  (validated structured metadata, e.g. a DOCX title style, an email subject,
  or an HTML `<title>`), never a free read of arbitrary body text.
- any explicit `task_tags` the calling workflow already knows about (e.g. from
  `remember_document_use`).

The legacy `DocumentAdapter` (used by `import_fernmark`) is unchanged, so its
tag surface stays backwards compatible.

## Bounded content access and use tracking

`read_document(document_id_or_sha256, offset, max_chars)` gives an agent
paged, bounded access to an already-imported, consented document's canonical
Markdown -- by document reference only, never a filesystem path. `max_chars`
is capped server-side (`document_read_max_chars`, default 20000); a request
above the cap is rejected, not silently truncated further. Every call is
audit-logged. The returned text is untrusted document content: it must never
be allowed to alter configuration, consent, or memory truth server-side.
Archived/superseded documents remain readable; the response reports `status`
and `disabled` so a caller can explain why a document might not be current.

`remember_document_use(document_id_or_sha256, purpose, task_tags,
artifact_pointer, use_summary)` records that a document was used for
something, as a byproduct of work already performed in the turn -- it must
never be a reason to make a separate model call. It writes one normal
`observe()` event proposing `task:<purpose-slug>` plus the document's own
`doc:` tag, so the use co-occurs with the document in the graph.

## Vault contract

Set `FERNME_VAULT` to choose the vault root. When it is unset, a file-backed
service uses the directory containing the resolved `FERNME_DB`. Managed files
live below:

```text
documents/<owner-hash>/<safe-source-stem>.md
documents/<owner-hash>/<safe-source-stem>.fernmark.json
```

A different document with the same safe stem receives `--<sha12>`. Writes use
same-directory temporary files plus atomic replacement. Pointers are always
vault-relative. Import cleanup removes only files created by the failed call,
and no FERNme operation treats the original supplied source as a managed file.

## Retrieval and lifecycle

`recall_documents` is consent-gated, bounded to at most 50 rows per call, and
supports continuation cursors. It ranks approved tag and safe metadata matches,
then explicit pin/authority and active state. It returns compact metadata and
relative pointers, never Markdown bodies.

Active documents may be archived, explicitly superseded, pinned, or marked
authoritative by the user. Archived and superseded rows are hidden by default.
`forget_document` removes the catalog row, tag mappings, source-specific
suggestions, Cabinet events, and accepted-tag graph evidence. Managed Markdown
and envelope files are removed only with `delete_managed_files=true`; the
original source is never deleted.

## Storage migration

SQLite and PostgreSQL create two additive tables with idempotent schema setup:

- `documents` for durable catalog metadata and lifecycle state;
- `document_tags` for human-approved tag provenance.

No existing table or graph weight is rewritten. Tenant isolation is enforced
by `site` and `user` on every catalog and mapping operation.

## Legacy backfill

`FernService.backfill_documents(site, user, dry_run)` (also `python -m
fernme.backfill_documents`, or the `backfill_documents` MCP tool) finds
`document` Cabinet events written before the managed catalog existed --
pre-Phase-18 `import_fernmark` imports, identified by a `source_sha256`
payload with no `document_id` -- and creates one catalog row per event.
Events and graph edges are left exactly as they are; backfill only adds
catalog metadata on top. Backfilled rows have an empty `markdown_path` /
`envelope_path` (no vault artifact was ever written for them); `read_document`
falls back to the original event's stored Markdown for those rows. Dry-run by
default, idempotent (a document already cataloged, or already backfilled, is
skipped), consent-respecting, and audit-logged. It reports counts only.
