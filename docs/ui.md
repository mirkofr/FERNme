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
