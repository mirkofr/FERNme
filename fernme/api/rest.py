"""FastAPI REST interface for FERN v1. Run:
  uvicorn fern.api.rest:app --port 8077
Every endpoint is consent-gated by the service layer."""
from __future__ import annotations
import os
from typing import List, Optional, Any, Dict
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from ..runtime_config import default_site, default_user
from ..service import FernService, ConsentError

svc = FernService()  # default: $FERNME_DB or ~/.fernme/fernme.db
app = FastAPI(title="FERN Memory API", version="1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
_APP_INDEX = os.path.join(os.path.dirname(__file__), "..", "web", "static", "app", "index.html")
_STATIC = os.path.join(os.path.dirname(__file__), "..", "web", "static")
_API_KEY = os.environ.get("FERNME_API_KEY")  # if set, all data routes require X-API-Key
_OPEN = {
    "/",
    "/health",
    "/ui",
    "/graph",
    "/runtime-defaults",
    "/docs",
    "/redoc",
    "/openapi.json",
    "/docs/oauth2-redirect",
}
app.mount("/static", StaticFiles(directory=_STATIC), name="static")


@app.middleware("http")
async def _auth(request, call_next):
    if _API_KEY and request.url.path not in _OPEN and not request.url.path.startswith("/static/"):
        if request.headers.get("x-api-key") != _API_KEY:
            return JSONResponse({"detail": "invalid or missing X-API-Key"}, status_code=401)
    return await call_next(request)


@app.get("/ui")
def ui():
    return FileResponse(_APP_INDEX, headers={"Cache-Control": "no-store"})

@app.get("/ui/{path:path}")
def ui_route(path: str):
    return FileResponse(_APP_INDEX, headers={"Cache-Control": "no-store"})

@app.get("/")
def root():
    return RedirectResponse("/ui/graph")

class GraphIn(BaseModel):
    site: str; user: Optional[str] = None; hierarchy: bool = True; assoc_floor: float = 1.0

class WhyIn(BaseModel):
    site: str; user: str; attr: str; now: float = 0.0

class ConfidenceIn(BaseModel):
    site: str; user: str; attr: str; now: float = 0.0

class ReplayIn(BaseModel):
    site: str; user: str; context: List[str] = []; now: float = 0.0

class MemoryGraphIn(BaseModel):
    person: str

@app.get("/graph")
def graph_ui():
    return RedirectResponse("/ui/graph")

@app.get("/runtime-defaults")
def runtime_defaults():
    site = default_site()
    user = default_user()
    env_site = "FERNME_SITE" in os.environ
    env_user = "FERNME_USER" in os.environ
    if not (env_site and env_user):
        contexts = getattr(svc.store, "list_consented_contexts", lambda limit=2: [])(limit=2)
        if len(contexts) == 1:
            if not env_site:
                site = contexts[0]["site"]
            if not env_user:
                user = contexts[0]["user"]
    return {"site": site, "user": user}

@app.post("/graph-data")
def graph_data(b: GraphIn):
    return _guard(svc.graph, b.site, b.user, assoc_floor=b.assoc_floor, hierarchy=b.hierarchy)

@app.post("/memory-graph")
def memory_graph(b: MemoryGraphIn):
    return _guard(svc.memory_graph, b.person)


class ConsentIn(BaseModel):
    site: str; user: str; granted: bool = True; ts: float = 0.0

class ObserveIn(BaseModel):
    site: str; user: str; type: str = "purchase"; payload: Dict[str, Any] = {}; ts: float = 0.0

class NumericIn(BaseModel):
    site: str; user: str; key: str; value: Any

class CardIn(BaseModel):
    site: str; user: str; context: List[str] = []; now: float = 0.0

class EditIn(BaseModel):
    site: str; user: str; attr: str; weight: float

class RecallIn(BaseModel):
    site: str; user: str; type: Optional[str] = None; contains: Optional[str] = None; limit: int = 20

class UserRef(BaseModel):
    site: str; user: str

class TriggersIn(BaseModel):
    site: str; user: str; now: float = 0.0

class SuggestionListIn(BaseModel):
    site: str; user: str; now: float = 0.0; refresh: bool = True

class SuggestionDecisionIn(BaseModel):
    site: str; user: str; suggestion_id: str; ts: float = 0.0


def _guard(fn, *a, **k):
    try:
        return fn(*a, **k)
    except ConsentError as e:
        raise HTTPException(status_code=403, detail=str(e))


@app.get("/health")
def health(): return {"ok": True, "service": "fern", "version": "1.0"}

@app.post("/consent")
def consent(b: ConsentIn): return svc.consent(b.site, b.user, b.granted, b.ts)

@app.post("/observe")
def observe(b: ObserveIn): return _guard(svc.observe, b.site, b.user, b.type, b.payload, b.ts)

@app.post("/numeric")
def numeric(b: NumericIn): return _guard(svc.set_numeric, b.site, b.user, b.key, b.value)

@app.post("/card")
def card(b: CardIn): return _guard(svc.card, b.site, b.user, b.context, b.now)

@app.post("/defaults")
def defaults(b: CardIn): return _guard(svc.defaults, b.site, b.user, b.now)

@app.post("/recall")
def recall(b: RecallIn): return _guard(svc.recall, b.site, b.user, b.type, b.contains, b.limit)

@app.post("/edit")
def edit(b: EditIn): return _guard(svc.edit, b.site, b.user, b.attr, b.weight)

@app.post("/why")
def why(b: WhyIn): return _guard(svc.why, b.site, b.user, b.attr, b.now)

@app.post("/confidence")
def confidence(b: ConfidenceIn): return _guard(svc.confidence, b.site, b.user, b.attr, b.now)

@app.post("/audit")
def audit(b: UserRef): return _guard(svc.audit_log, b.site, b.user)

@app.post("/recall-replay")
def recall_replay(b: ReplayIn): return _guard(svc.recall_replay, b.site, b.user, b.context, b.now)

@app.post("/export")
def export(b: UserRef): return _guard(svc.export, b.site, b.user)

@app.post("/delete")
def delete(b: UserRef): return svc.delete(b.site, b.user)

@app.post("/triggers")
def triggers(b: TriggersIn): return _guard(svc.triggers, b.site, b.user, b.now)

@app.post("/suggestions/list")
def list_suggestions(b: SuggestionListIn):
    return _guard(svc.list_suggestions, b.site, b.user, b.now, b.refresh)

@app.post("/suggestions/accept")
def accept_suggestion(b: SuggestionDecisionIn):
    return _guard(svc.accept_suggestion, b.site, b.user, b.suggestion_id, b.ts)

@app.post("/suggestions/reject")
def reject_suggestion(b: SuggestionDecisionIn):
    return _guard(svc.reject_suggestion, b.site, b.user, b.suggestion_id, b.ts)

@app.post("/prior_refresh")
def prior_refresh(b: UserRef): return svc.prior_refresh(b.site)
