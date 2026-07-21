# Local UI

FERNme ships a local React single-page app through the Python REST server. The app
is built from `fernme/web/app` and emitted into `fernme/web/static/app`, which is
included in the Python package so installed users do not need Node.js at runtime.

Build or refresh the checked-in UI bundle with:

```powershell
cd fernme/web/app
npm ci
npm run build
```

Run the local server with:

```powershell
fernme-ui --db redacted-db-value --site example.local --user demo-user
```

The server opens `/ui/graph`. The legacy `/graph` route redirects there for old
bookmarks. The UI bundle and graph runtime are local package assets; it does not
load JavaScript from a CDN.

## Document evidence overlay

The graph page includes a `Document evidence` switch that is off by default.
When enabled, it requests a bounded set of active document hubs and approved
tag provenance links from the durable catalog. Selecting a tag narrows the
overlay to relevant documents; selecting a document shows only safe metadata
and its vault-relative Markdown pointer. Document bodies and absolute paths are
never embedded in graph data.

If more relevant documents exist, `Load more documents` increases the bounded
request up to the service maximum. Archived or superseded documents stay hidden
unless an explicit API caller asks for them. The switch does not change normal
graph association thresholds or compact-card recall.
