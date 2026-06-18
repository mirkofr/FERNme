"""FernService — the full v1 API, persistence-backed and consent-gated.
Ties the engine (write/retrieve/prior) to the SQLite store. This is what the
REST and MCP layers call."""
from __future__ import annotations
from typing import List, Dict, Optional
from .core.graph import UserGraph, AssocGraph, Event, Edge
from .write import Catalog, map_event, observe, decay
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
from .vocabulary import Vocabulary
from dataclasses import replace as _replace
from .triggers import due_reorders, fading_favorites
import os


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
                payload["tags"] = sanitize_tags(list(payload.get("tags", [])) + st["style_tags"])
                ev = Event(site, user, ts, type, payload)
                mapped = map_event(ev, self.catalog)
        if self.vocabulary is not None:           # ingestion bridge: canonicalize tags
            mapped = [(c, m) for (a, m) in mapped if (c := self.vocabulary.canonical(a))]
        observe(ug, ag, ev, mapped, self.cfg)
        if st is not None:                      # update mood EMA + trend (domain-agnostic)
            old = ug.numeric.get("mood_ema")
            new = st["mood"] if old is None else round(0.5 * st["mood"] + 0.5 * old, 3)
            ug.numeric["mood_prev"] = old if old is not None else new
            ug.numeric["mood_ema"] = new
        self.store.save_user(ug)
        self.store.save_assoc(ag)
        self.store.append_event(ev)
        self._audit(site, user, "observe", {"type": type, "n_attrs": len(mapped)}, ts)
        return {"stored_attrs": [a for a, _ in mapped], "edges": ug.n_edges()}

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
                              source="override", last_reinforced=now_or_zero(ug, attr))
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
        dropped = decay(ug, now, self.cfg)
        self.store.save_user(ug)
        return {"dropped": dropped, "remaining": ug.n_edges()}

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
        tags = [a for a in ug.edges if a.startswith("style:")]
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
        self.store.save_user(ug)
        self.store.append_event(Event(site, user, now, "outcome",
                                       {"success": bool(success), "attrs": list(attrs)}))
        return {"success": bool(success), "attrs": list(attrs)}

    def why(self, site: str, user: str, attr: str) -> Dict:
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
        return {"attr": attr, "observations": obs, "good_outcomes": good,
                "bad_outcomes": bad, "first_seen": first, "last_seen": last}

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
            neg = ug.edges.get("!" + attr)   # conflict: a negative counterpart = a flip
            conflict = conflict or (min(1.0, neg.weight / self.cfg.w_max) if neg else 0.0)
            c = _confidence.compute(e, now, self.cfg, taxonomy_match, outcome_success, conflict)
            g = _confidence.gate(c, self.cfg, importance)
        if g == "ask" and self._ask_count.get((site, user), 0) >= self.cfg.ask_budget:
            g = "observe"        # out of ask budget -> don't pester
        return {"confidence": round(c, 3), "gate": g, "conflict": round(conflict, 3)}

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
