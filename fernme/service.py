"""FernService — the full v1 API, persistence-backed and consent-gated.
Ties the engine (write/retrieve/prior) to the SQLite store. This is what the
REST and MCP layers call."""
from __future__ import annotations
from typing import List, Dict, Optional
from .core.graph import UserGraph, AssocGraph, Event, Edge
from .write import Catalog, map_event, observe, decay
from .categories import category_of, CATEGORIES
from .hierarchy import build_hierarchy
from .retrieve.card import compile_card
from .config import Config, DEFAULT
from .store.sqlite_store import SQLiteStore
from .supernode import Supernode
from .safety import sanitize_tags, cap_numeric
from .tagging import DeterministicTagger
from . import style as _style
from .dp import PrivatePrior
from . import audit as _audit_mod
from . import confidence as _confidence
from . import curation as _curation
from . import glossary as _glossary
from . import resolution as _resolution
from .vocabulary import Vocabulary
from .identity import is_identity_attr
from dataclasses import replace as _replace
from .triggers import due_reorders, fading_favorites
import os


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, float(x)))


def _conflict_for_edge(ug: UserGraph, attr: str, cfg: Config) -> float:
    edge = ug.edges.get(attr)
    if edge is None:
        return 0.0
    return max(
        (_curation.conflict_score(attr, edge, other, other_edge, cfg.w_max)
         for other, other_edge in ug.edges.items()
         if other != attr and edge.last_reinforced < other_edge.last_reinforced),
        default=0.0,
    )


def default_db_path() -> str:
    """Local, non-cloud-synced path. SQLite on iCloud/Dropbox/OneDrive corrupts."""
    return os.environ.get("FERNME_DB") or os.path.join(
        os.path.expanduser("~"), ".fernme", "fernme.db")


class ConsentError(RuntimeError):
    pass


class FernService:
    def __init__(self, db_path: str = None, cfg: Config = DEFAULT, store=None,
                 memory_mode: str = "pure", tagger=None, enricher=None, catalog=None,
                 vocabulary=None):
        # memory_mode: "pure" (default, no LLM, key-less, tested) | "gated"
        # (LLM tags only novel free-text, opt-in/experimental) | "offline"
        # (pure writes + a batched consolidate() enrichment pass).
        assert memory_mode in ("pure", "gated", "offline")
        self.store = store or SQLiteStore(db_path or default_db_path())
        self.cfg = cfg
        self.memory_mode = memory_mode
        self.tagger = tagger                  # LLMTagger for gated; None in pure
        self.enricher = enricher              # LLMTagger for offline consolidation
        self.track_style = True               # learn communication style + mood from text
        # per-site catalog/taxonomy: maps item_id -> attribute tags (no LLM).
        self.catalog = catalog if isinstance(catalog, Catalog) else Catalog(catalog)
        # controlled vocabulary: normalize every tag to one canonical namespaced form.
        self.vocabulary = vocabulary
        self.audit_key = b"fernme-default-audit-key"  # per-user key in production
        self._ask_count = {}                  # ask-budget rate limit per (site,user)
        self.llm_calls = 0                    # transparency: count LLM invocations

    # ---------- consent / governance ----------
    def consent(self, site: str, user: str, granted: bool, ts: float = 0.0) -> Dict:
        self.store.set_consent(site, user, granted, ts)
        self._audit(site, user, "consent", {"granted": bool(granted)}, ts)
        if not granted:                       # withdrawing consent purges the profile
            self.store.delete_user(site, user)
        return {"site": site, "user": user, "consent": granted}

    def _require_consent(self, site: str, user: str):
        if not self.store.has_consent(site, user):
            raise ConsentError(f"no consent on record for {site}/{user}")

    # ---------- write path ----------
    def _salience_of(self, payload: Dict, mapped, style_state: Dict = None) -> Dict:
        """Behavioral significance per attribute (no LLM): explicit intensity/rating in
        the payload, emotional arousal in the text, and identity floors. Negative
        edges get a floor in the write rule; outcomes add salience."""
        s0 = payload.get("intensity")
        if isinstance(s0, (int, float)):
            s0 = _clamp01(s0)
        else:
            r = payload.get("rating")
            s0 = _clamp01(abs(float(r) - 3.0) / 2.0) if isinstance(r, (int, float)) else 0.0
        if style_state:
            norm = max(float(self.cfg.salience_intensity_norm), 1e-9)
            s_emotion = _clamp01(
                self.cfg.salience_w_intensity * min(1.0, float(style_state["intensity"]) / norm)
                + self.cfg.salience_w_moodmag * abs(float(style_state["mood"]))
            )
            s0 = max(s0, s_emotion)

        salience = {attr: s0 for attr, _ in mapped} if s0 > 0 else {}
        for attr, _ in mapped:
            if is_identity_attr(attr):
                salience[attr] = max(salience.get(attr, 0.0), self.cfg.salience_identity)
        return salience

    def observe(self, site: str, user: str, type: str, payload: Dict,
                ts: float = 0.0) -> Dict:
        """Record one interaction. payload may carry 'tags' (and/or 'item_id');
        mapping is deterministic, no LLM. Updates graph + Cabinet."""
        self._require_consent(site, user)
        ug = self.store.load_user(site, user)
        ag = self.store.load_assoc(site)
        payload = dict(payload)
        if "tags" in payload:
            payload["tags"] = sanitize_tags(payload["tags"])
        ev = Event(site, user, ts, type, payload)
        mapped = map_event(ev, self.catalog)
        # GATED: only when the deterministic path found nothing AND there is
        # free text to interpret do we spend one (small) LLM call.
        if (not mapped and self.memory_mode == "gated" and self.tagger is not None
                and payload.get("text")):
            tags = self.tagger.tag(payload["text"], payload)
            self.llm_calls += 1
            if tags:
                payload["tags"] = sanitize_tags(list(payload.get("tags", [])) + tags)
                ev = Event(site, user, ts, type, payload)
                mapped = map_event(ev, self.catalog)
        ev.attrs = mapped
        st = None
        if self.track_style and payload.get("text"):
            st = _style.analyze(payload["text"])
            if st["style_tags"]:
                payload["style_tags"] = sanitize_tags(st["style_tags"])
                ev = Event(site, user, ts, type, payload)
        if self.vocabulary is not None:           # ingestion bridge: canonicalize tags
            merged, alias_map = {}, {}
            for attr, mag in mapped:
                canonical, alias = self.vocabulary.resolve(attr)
                if not canonical:
                    continue
                merged[canonical] = max(float(mag), merged.get(canonical, 0.0))
                if alias:
                    alias_map[alias] = canonical
            mapped = list(merged.items())
            if alias_map:
                payload["aliases"] = alias_map
                ev = Event(site, user, ts, type, payload)
        ev.attrs = mapped
        # snapshot existing memory BEFORE the write, for conflict/authority checks
        existing_snapshot = ({a: _replace(e) for a, e in ug.edges.items()}
                             if self.cfg.curation else {})
        new_source = payload.get("source", "known")
        observe(ug, ag, ev, mapped, self.cfg,
                salience=self._salience_of(payload, mapped, st),
                provenance=new_source)
        questions, superseded = ([], [])
        if self.cfg.curation:
            questions, superseded = self._curate(site, user, ug, mapped, new_source,
                                                  existing_snapshot, ts)
        if st is not None:                      # update mood EMA + trend (domain-agnostic)
            old = ug.numeric.get("mood_ema")
            new = st["mood"] if old is None else round(0.5 * st["mood"] + 0.5 * old, 3)
            ug.numeric["mood_prev"] = old if old is not None else new
            ug.numeric["mood_ema"] = new
        self.store.save_user(ug)
        self.store.save_assoc(ag)
        self.store.append_event(ev)
        self._audit(site, user, "observe", {"type": type, "n_attrs": len(mapped)}, ts)
        out = {"stored_attrs": [a for a, _ in mapped], "edges": ug.n_edges()}
        if self.cfg.curation:
            out["questions"] = questions
            out["superseded"] = superseded
        return out

    def _curate(self, site, user, ug, mapped, new_source, existing, ts):
        """Apply the editing policy to the just-written attrs: supersede a losing
        memory (demote + tombstone in the event log) or raise a question. Returns
        (questions, superseded). Deterministic, no LLM."""
        questions, superseded = [], []
        for attr, _mag in mapped:
            imp = self._conflict_importance(attr)
            for r in _curation.review(attr, new_source, ts, existing, importance=imp,
                                      ask_threshold=self.cfg.curation_ask_threshold):
                if r.action == "supersede" and r.old_attr in ug.edges:
                    old = ug.edges[r.old_attr]
                    old.weight = min(old.weight, self.cfg.floor)  # demote below recall
                    old.source = "superseded"
                    superseded.append({"old": r.old_attr, "by": attr, "kind": r.kind})
                    self.store.append_event(Event(site, user, ts, "supersede",
                        {"old": r.old_attr, "new": attr, "kind": r.kind}))
                elif r.action == "ask":
                    questions.append({"new": attr, "old": r.old_attr,
                                      "kind": r.kind, "question": r.question})
                    self.store.append_event(Event(site, user, ts, "question",
                        {"new": attr, "old": r.old_attr, "question": r.question}))
        return questions, superseded

    @staticmethod
    def _conflict_importance(attr: str) -> float:
        """Identity facts and explicit dislikes are worth asking about; rest mid."""
        ns = attr.lstrip("!").split(":", 1)[0]
        if attr.startswith("!") or ns in _curation.SINGLE_VALUE_SLOTS:
            return 0.8
        return 0.5

    def set_numeric(self, site: str, user: str, key: str, value) -> Dict:
        self._require_consent(site, user)
        ug = self.store.load_user(site, user)
        ug.numeric[key] = cap_numeric(value)
        self.store.save_user(ug)
        return {"numeric": ug.numeric}

    # ---------- read path ----------
    def card(self, site: str, user: str, context: Optional[List[str]] = None,
             now: float = 0.0, cold_start: bool = True) -> Dict:
        self._require_consent(site, user)
        ug = self.store.load_user(site, user)
        ag = self.store.load_assoc(site)
        prior = self.store.load_prior(site)
        if cold_start and ug.n_edges() == 0 and prior.n_users > 0:
            prior.cold_start(ug, self.cfg)     # turn-one usefulness from the population
        return compile_card(ug, ag, context or [], now, prior, self.cfg)

    def recall(self, site: str, user: str, type: Optional[str] = None,
               contains: Optional[str] = None, limit: int = 20) -> List[Dict]:
        """Open the Cabinet: structured query over raw events (specific facts)."""
        self._require_consent(site, user)
        return self.store.recall(site, user, type, contains, limit)

    def defaults(self, site: str, user: str, now: float = 0.0) -> Dict:
        """Baked-in: known links -> tool defaults / ranking bias."""
        card = self.card(site, user, now=now)
        known = [l["attr"] for l in card["links"] if l["known"]]
        return {"bias_toward": known, "numeric": card["numeric"]}

    # ---------- glass-box ----------
    def edit(self, site: str, user: str, attr: str, weight: float) -> Dict:
        """User override: locked, never decays."""
        self._require_consent(site, user)
        ug = self.store.load_user(site, user)
        ug.edges[attr] = Edge(weight=float(weight), confidence=1.0,
                              source="override", last_reinforced=now_or_zero(ug, attr),
                              provenance="stated")
        self.store.save_user(ug)
        self._audit(site, user, "edit", {"attr": attr, "weight": weight})
        return {"attr": attr, "weight": weight, "source": "override"}

    def export(self, site: str, user: str) -> Dict:
        self._require_consent(site, user)
        return self.store.export_user(site, user)

    def delete(self, site: str, user: str) -> Dict:
        self.store.delete_user(site, user)
        return {"deleted": True, "site": site, "user": user}

    # ---------- batch jobs ----------
    def decay(self, site: str, user: str, now: float) -> Dict:
        ug = self.store.load_user(site, user)
        conflict_map = self._decay_conflicts(ug) if self.cfg.resolution else {}
        dropped = decay(ug, now, self.cfg, conflict_map=conflict_map,
                        ctx={"now": now})
        self.store.save_user(ug)
        return {"dropped": dropped, "remaining": ug.n_edges()}

    def _decay_conflicts(self, ug) -> Dict[str, float]:
        conflicts = {}
        for attr, e in ug.edges.items():
            other = attr[1:] if attr.startswith("!") else "!" + attr
            oe = ug.edges.get(other)
            if oe is not None:
                conflicts[attr] = max(conflicts.get(attr, 0.0),
                                      min(1.0, oe.weight / self.cfg.w_max))
        if self.cfg.curation:
            attrs = list(ug.edges.keys())
            for attr in attrs:
                if _curation.detect(attr, attrs):
                    conflicts[attr] = max(conflicts.get(attr, 0.0), 1.0)
        return conflicts

    # ---------- supernode (user-owned cross-site) ----------
    def link_identity(self, person: str, site: str, local_user: str, ts: float = 0.0) -> Dict:
        """Called when the person signs in to `site` with their FERN account."""
        self.store.link_identity(person, site, local_user, ts)
        return {"person": person, "linked": self.store.list_identities(person)}

    def unlink_identity(self, person: str, site: str, local_user: str) -> Dict:
        self.store.unlink_identity(person, site, local_user)
        return {"person": person, "linked": self.store.list_identities(person)}

    def set_share(self, person: str, target_site: str, category: str, allowed: bool) -> Dict:
        self.store.set_share(person, target_site, category, allowed)
        return {"person": person, "target_site": target_site,
                "policy": self.store.get_shares(person, target_site)}

    def build_supernode(self, person: str) -> Supernode:
        sn = Supernode(person)
        for site, local_user in self.store.list_identities(person):
            sn.add_from_site(site, self.store.load_user(site, local_user))
        return sn

    def memory_graph(self, person: str) -> Dict:
        """The owner's ONE memory as a cross-surface graph: a central `you`, the
        surfaces it was learned on (sites / PC / phone), and every preference,
        tagged with provenance. Drives the /graph visualization."""
        sn = self.build_supernode(person)
        FAMCOL = {"web": "--teal", "pc": "--amber", "phone": "--violet"}
        PALETTE = ["--teal", "--info", "--amber", "--violet"]

        def family(site: str) -> str:
            x = site.lower()
            if any(t in x for t in ("pc", "desktop", "laptop", "mac", "windows")):
                return "pc"
            if any(t in x for t in ("phone", "ios", "android", "mobile")):
                return "phone"
            return "web"

        surf_keys = sorted({site for slot in sn.attrs.values() for site in slot["sources"]})
        colors = {}
        for i, k in enumerate(surf_keys):
            colors[k] = PALETTE[i % len(PALETTE)]
        surfaces = [{"key": k, "label": k, "family": family(k), "color": colors[k]}
                    for k in surf_keys]

        nodes = [{"id": "you", "label": person, "kind": "owner", "size": 11}]
        for sf in surfaces:
            nodes.append({"id": "surf:" + sf["key"], "label": sf["label"],
                          "kind": "surface", "surf": sf["key"],
                          "family": sf["family"], "size": 7})
        edges = []
        for attr, slot in sn.attrs.items():
            neg = attr.startswith("!"); base = attr.lstrip("!")
            pid = "p:" + attr
            srcs = list(slot["sources"].keys())
            primary = max(slot["sources"].items(), key=lambda kv: kv[1])[0]
            nodes.append({"id": pid, "label": base, "kind": "pref",
                          "size": round(slot["weight"], 1), "surfaces": srcs,
                          "color": colors[primary], "negative": neg,
                          "sensitive": slot["sensitive"]})
            edges.append({"source": "you", "target": pid,
                          "weight": round(slot["weight"], 1),
                          "known": slot["confidence"] >= self.cfg.conf_known,
                          "negative": neg})
            for site in srcs:
                edges.append({"source": pid, "target": "surf:" + site,
                              "surface": site, "prov": True})
        return {"nodes": nodes, "edges": edges, "surfaces": surfaces,
                "stats": {"memories": len(sn.attrs), "surfaces": len(surfaces)}}

    def supernode_card(self, person: str) -> Dict:
        """The OWNER's full cross-site view, with provenance."""
        return self.build_supernode(person).owner_card(self.cfg)

    def view_for_site(self, person: str, target_site: str) -> Dict:
        """The scoped slice `target_site` is permitted to see."""
        sn = self.build_supernode(person)
        return sn.view_for_site(target_site, self.store.get_shares(person, target_site), self.cfg)

    def consolidate(self, site: str, user: str, lookback: int = 200, ts: float = 0.0) -> Dict:
        """OFFLINE enrichment (run as a batch job): read recent event text, let the
        enricher propose nuanced/causal attributes, and fold them in via the normal
        write path. Off the hot path -> ~zero marginal per-interaction cost."""
        self._require_consent(site, user)
        if self.memory_mode != "offline" or self.enricher is None:
            return {"enriched": [], "note": "offline mode + enricher required"}
        events = self.store.recall(site, user, limit=lookback)
        text = " . ".join(str(e["payload"].get("text", "")) for e in events if e["payload"].get("text"))
        if not text.strip():
            return {"enriched": []}
        tags = self.enricher.tag(text, {})
        self.llm_calls += 1
        if tags:
            self.observe(site, user, "consolidation", {"tags": tags}, ts=ts)
        return {"enriched": tags, "llm_calls": self.llm_calls}

    def style_card(self, site: str, user: str) -> Dict:
        """How this person communicates + current mood/trend + tone guidance.
        Domain-agnostic: works for support, tutoring, booking, sales, anything."""
        self._require_consent(site, user)
        ug = self.store.load_user(site, user)
        tags = []
        seen = set()
        for ev in self.store.recall(site, user, limit=20):
            for tag in ev["payload"].get("style_tags", []):
                if tag not in seen:
                    tags.append(tag)
                    seen.add(tag)
        mood = float(ug.numeric.get("mood_ema", 0.0) or 0.0)
        prev = float(ug.numeric.get("mood_prev", mood) or mood)
        trend = round(mood - prev, 3)
        return {"mood": mood, "mood_trend": trend, "style": tags,
                "guidance": _style.guidance(mood, trend, tags)}

    def record_outcome(self, site: str, user: str, success: bool,
                       attrs=None, now: float = 0.0, weight: float = 1.0) -> Dict:
        """Domain-agnostic OUTCOME signal. `success` = did acting on memory achieve
        the goal? (purchase, booking, resolved ticket, completed lesson, kept appt...)
        Reinforces the involved attributes on success, penalizes on failure."""
        self._require_consent(site, user)
        ug = self.store.load_user(site, user)
        if attrs is None:
            evs = self.store.recall(site, user, limit=1)
            attrs = [a for a, _ in (evs[0]["attrs"] if evs else [])]
        for attr in attrs:
            e = ug.edges.get(attr)
            if e is None:
                continue
            if success:
                e.weight = min(self.cfg.w_max, e.weight + self.cfg.alpha * 0.5 * weight * (1 - e.weight / self.cfg.w_max))
            else:
                e.weight = max(0.0, e.weight * (1 - 0.3 * weight))
            e.salience = max(e.salience, min(1.0, 0.5 * weight + (0.0 if success else 0.2)))
        self.store.save_user(ug)
        self.store.append_event(Event(site, user, now, "outcome",
                                       {"success": bool(success), "attrs": list(attrs)}))
        return {"success": bool(success), "attrs": list(attrs)}

    def glossary(self, site: str, user: str, auto: bool = None) -> Dict:
        """What each remembered tag MEANS, assembled from stored events (no LLM).
        Returns {attr: {gloss, context, ts}}: 'context' is the sentence the memory
        came from (event text), 'gloss' is the supplied or namespace-templated
        one-liner. Closes the 'a bare tag carries no information' gap."""
        self._require_consent(site, user)
        if auto is None:
            auto = self.cfg.auto_gloss
        events = self.store.recall(site, user, limit=100000)
        return _glossary.assemble(events, auto=auto)

    def why(self, site: str, user: str, attr: str, now: float = 0.0) -> Dict:
        """Explainability (#8): the evidence behind a stored attribute."""
        self._require_consent(site, user)
        obs = good = bad = 0; first = last = None
        for e in self.store.recall(site, user, limit=100000):
            tags = [a for a, _ in e.get("attrs", [])] + list(e["payload"].get("attrs", [])) + list(e["payload"].get("tags", []))
            if attr not in tags:
                continue
            if e["type"] == "outcome":
                good += int(bool(e["payload"].get("success")))
                bad += int(not e["payload"].get("success"))
            else:
                obs += 1
            ts = e["ts"]; first = ts if first is None else min(first, ts); last = ts if last is None else max(last, ts)
        out = {"attr": attr, "observations": obs, "good_outcomes": good,
               "bad_outcomes": bad, "first_seen": first, "last_seen": last}
        if getattr(self.cfg, "volatility_confidence", False):
            ug = self.store.load_user(site, user)
            edge = ug.edges.get(attr)
            if edge is not None:
                conflict = _conflict_for_edge(ug, attr, self.cfg)
                conf = _confidence.compute(edge, now, self.cfg, attr=attr,
                                           conflict=conflict)
                detail = _resolution.needs_verify(attr, edge, now, self.cfg, conf,
                                                  conflict=conflict)
                out.update({
                    "confidence": round(conf, 3),
                    "verify": bool(detail["verify"]),
                    "age_halflives": round(detail["age_halflives"], 3),
                    "verify_reason": detail["reason"],
                })
        return out

    def triggers(self, site: str, user: str, now: float) -> Dict:
        """Proactive nudges: due reorders + fading favorites."""
        self._require_consent(site, user)
        ug = self.store.load_user(site, user)
        events = self.store.recall(site, user, limit=10000)
        return {"due_reorders": due_reorders(ug.numeric, events, now),
                "fading_favorites": fading_favorites(ug, now)}

    # ---------- verifiable data ownership (#4) ----------
    def _audit(self, site, user, action, detail, ts=0.0):
        if hasattr(self.store, "append_audit"):
            return self.store.append_audit(site, user, ts, action, detail, self.audit_key)

    def audit_log(self, site: str, user: str):
        return self.store.read_audit(site, user) if hasattr(self.store, "read_audit") else []

    def verify_audit(self, site: str, user: str) -> Dict:
        """Replay the tamper-evident chain. ok=False means it was altered."""
        ok, broken = _audit_mod.verify(self.audit_log(site, user), self.audit_key)
        return {"ok": ok, "broken_at_seq": broken}

    def forget_everywhere(self, site: str, user: str) -> Dict:
        """Right to be forgotten, provably: record the deletion in the audit chain,
        wipe the profile, then UNLEARN the user's contribution from the population
        prior (cascading). The audit chain (no PII) remains as proof it happened."""
        self._audit(site, user, "forget", {})
        self.store.delete_user(site, user)
        refreshed = self.prior_refresh(site)          # recompute prior without them
        return {"forgotten": True, "site": site, "user": user, "prior": refreshed}

    def set_vocabulary(self, vocab):
        """Register the controlled namespaced vocabulary used to canonicalize tags."""
        self.vocabulary = vocab
        return {"terms": len(getattr(vocab, "terms", []))}

    def set_catalog(self, items: dict):
        """Register the site's item_id -> tags taxonomy (the structured-ingestion
        layer). Deterministic, no LLM."""
        self.catalog = Catalog(items)
        return {"items": len(items)}

    def prune_to_prior(self, site: str, user: str, theta: float = None) -> Dict:
        """Differential storage (#spec): drop user edges that are within `theta` of
        the population prior -- they're redundant (read-through from the prior gives
        the same value), so only DEVIATIONS are kept. Overrides are never pruned."""
        theta = self.cfg.theta if theta is None else theta
        prior = self.store.load_prior(site)
        ug = self.store.load_user(site, user)
        pruned = []
        for attr, e in list(ug.edges.items()):
            if e.source == "override":
                continue
            if prior._n.get(attr, 0) > 0 and abs(e.weight - prior.mean(attr)) <= theta:
                pruned.append(attr); del ug.edges[attr]; ug.history.pop(attr, None)
        self.store.save_user(ug)
        return {"pruned": len(pruned), "remaining": ug.n_edges()}

    def graph(self, site: str, user: str = None, assoc_floor: float = 2.0,
              hierarchy: bool = True) -> Dict:
        """Memory as nodes + edges for visualization. user=None -> whole site
        (all consented users + shared attributes); user set -> that user's subgraph."""
        if user is not None:
            self._require_consent(site, user)
            users = [user]
        else:
            users = [u for u in self.store.list_users(site) if self.store.has_consent(site, u)]
        nodes, edges = {}, []
        for u in users:
            ug = self.store.load_user(site, u)
            if not ug.edges:
                continue
            uid = "user:" + u
            nodes[uid] = {"id": uid, "label": u, "kind": "user", "size": 9}
            for attr, e in ug.edges.items():
                if e.source == "superseded":
                    continue
                neg = attr.startswith("!"); base = attr.lstrip("!")
                ns = base.split(":", 1)[0] if ":" in base else "attr"
                n = nodes.setdefault(base, {"id": base, "label": base, "kind": ns, "size": 0,
                                            "category": category_of(attr)})
                if neg:
                    n["category"] = "emotional"
                n["size"] = max(n["size"], e.wire_weight(self.cfg.w_max))
                edges.append({"source": uid, "target": base, "weight": e.wire_weight(self.cfg.w_max),
                              "confidence": round(e.confidence, 2),
                              "known": (e.confidence >= self.cfg.conf_known or e.source == "override"),
                              "negative": neg})
        present = {n for n, v in nodes.items() if v["kind"] != "user"}
        ag = self.store.load_assoc(site)
        for (a, b), w in ag.edges.items():
            if a in present and b in present and w >= assoc_floor:
                edges.append({"source": a, "target": b, "weight": round(w, 1), "assoc": True})
        out = {"nodes": list(nodes.values()), "edges": edges,
               "categories": CATEGORIES, "cats": CATEGORIES,
               "stats": {"users": sum(1 for v in nodes.values() if v["kind"] == "user"),
                         "attributes": len(present), "edges": len(edges)}}
        if hierarchy:
            out["hierarchy"] = build_hierarchy(out)
        return out

    def confidence(self, site: str, user: str, attr: str, now: float = 0.0,
                   taxonomy_match=None, outcome_success=None, conflict: float = 0.0,
                   importance: float = 0.5) -> Dict:
        """Multi-signal confidence + 3-tier gate (act / observe / ask / ignore).
        Honors the ask-budget so 'ask' never nags beyond cfg.ask_budget."""
        self._require_consent(site, user)
        ug = self.store.load_user(site, user)
        e = ug.edges.get(attr)
        if e is None:
            c, conflict = 0.0, 0.0
            g = _confidence.gate(c, self.cfg, importance)
        else:
            conflict = conflict or _conflict_for_edge(ug, attr, self.cfg)
            c = _confidence.compute(e, now, self.cfg, taxonomy_match, outcome_success,
                                    conflict, attr=attr)
            g = _confidence.gate(c, self.cfg, importance)
        if g == "ask" and self._ask_count.get((site, user), 0) >= self.cfg.ask_budget:
            g = "observe"        # out of ask budget -> don't pester
        out = {"confidence": round(c, 3), "gate": g, "conflict": round(conflict, 3)}
        if getattr(self.cfg, "volatility_confidence", False) and e is not None:
            detail = _resolution.needs_verify(attr, e, now, self.cfg, c,
                                              conflict=conflict)
            out["verify"] = bool(detail["verify"])
            out["age_halflives"] = round(detail["age_halflives"], 3)
        return out

    def record_ask(self, site: str, user: str):
        self._ask_count[(site, user)] = self._ask_count.get((site, user), 0) + 1

    def private_prior(self, site: str, epsilon: float = 1.0, k: int = 5, seed: int = 0):
        """A differentially-private, rare-group-suppressed view of the population
        prior (#1). Safe to use for cross-user cold-start: no individual leaks."""
        return PrivatePrior(self.store.load_prior(site), epsilon=epsilon, k=k,
                            w_max=self.cfg.w_max, seed=seed)

    def autotune_decay(self, drift: bool = True) -> Dict:
        """Self-tuning forgetting (#6): search decay rates, set the best on this
        service's config. (Proxy objective here; production tunes on site outcomes.)"""
        from . import tuning
        res = tuning.tune_decay(drift=drift)
        self.cfg = _replace(self.cfg, lam=res["best_lam"])
        return res

    def prior_refresh(self, site: str) -> Dict:
        """Fold every consented user's graph into the population prior."""
        prior = self.store.load_prior(site)
        prior._sum.clear(); prior._n.clear(); prior.n_users = 0
        users = [r["user"] for r in self.store._conn.execute(
            "SELECT DISTINCT user FROM user_edges WHERE site=?", (site,))]
        for u in users:
            prior.update_from_user(self.store.load_user(site, u))
        self.store.save_prior(prior)
        return {"site": site, "n_users": prior.n_users, "attrs": len(prior._n)}


def now_or_zero(ug: UserGraph, attr: str) -> float:
    e = ug.edges.get(attr)
    return e.last_reinforced if e else 0.0
