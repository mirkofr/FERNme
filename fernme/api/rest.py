"""FastAPI REST interface for FERN v1. Run:
  uvicorn fern.api.rest:app --port 8077
Every endpoint is consent-gated by the service layer."""
from __future__ import annotations
import os
from typing import List, Optional, Any, Dict
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from ..service import FernService, ConsentError

svc = FernService()  # default: $FERNME_DB or ~/.fernme/fernme.db
app = FastAPI(title="FERN Memory API", version="1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
_UI = os.path.join(os.path.dirname(__file__), "..", "web", "glassbox.html")
_GRAPH_UI = os.path.join(os.path.dirname(__file__), "..", "web", "graph.html")
_API_KEY = os.environ.get("FERNME_API_KEY")  # if set, all data routes require X-API-Key
_OPEN = {"/health", "/ui", "/docs", "/redoc", "/openapi.json", "/docs/oauth2-redirect"}


@app.middleware("http")
async def _auth(request, call_next):
    if _API_KEY and request.url.path not in _OPEN:
        if request.headers.get("x-api-key") != _API_KEY:
            return JSONResponse({"detail": "invalid or missing X-API-Key"}, status_code=401)
    return await call_next(request)


@app.get("/ui")
def ui():
    return FileResponse(_UI)

class GraphIn(BaseModel):
    site: str; user: Optional[str] = None; hierarchy: bool = True

class WhyIn(BaseModel):
    site: str; user: str; attr: str; now: float = 0.0

class MemoryGraphIn(BaseModel):
    person: str

@app.get("/graph")
def graph_ui():
    return FileResponse(_GRAPH_UI)

@app.post("/graph-data")
def graph_data(b: GraphIn):
    return _guard(svc.graph, b.site, b.user, hierarchy=b.hierarchy)

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
