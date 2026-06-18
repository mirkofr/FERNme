"""Multi-signal confidence (#uncertainty gate).

Upgrades FERN's confidence from hit-count-only to a NORMALIZED, weighted blend of
cheap signals already in the graph. Drives a 3-tier gate so the expensive paths
(ask the user, call an LLM) fire ONLY when genuinely uncertain -> keeps LLM use
occasional. Weights live in config and are meant to be tuned later (e.g. with BO),
never optimized inside a write.

  confidence = w_e*evidence + w_c*consistency + w_t*taxonomy + w_r*recency + w_o*outcome
  gate: >=conf_high act | >=conf_low observe | else ask(if important) / ignore
"""
from __future__ import annotations
import math


def compute(edge, now, cfg, taxonomy_match=None, outcome_success=None, conflict=0.0):
    evidence = 1.0 - math.exp(-cfg.gamma * edge.hits)                 # weak if 1 obs
    recency = math.exp(-cfg.lam * max(0.0, now - edge.last_reinforced))  # stale -> low
    taxonomy = taxonomy_match if taxonomy_match is not None else (
        0.4 if edge.source == "guessed" else 1.0)                    # clean map -> high
    consistency = max(0.0, 1.0 - conflict)                           # A->B flip -> low
    outcome = 0.5 if outcome_success is None else outcome_success    # neutral default
    c = (cfg.w_evidence * evidence + cfg.w_consistency * consistency
         + cfg.w_taxonomy * taxonomy + cfg.w_recency * recency
         + cfg.w_outcome * outcome)
    return max(0.0, min(1.0, c))


def gate(confidence, cfg, importance: float = 0.5) -> str:
    if confidence >= cfg.conf_high:
        return "act"            # high -> act silently
    if confidence >= cfg.conf_low:
        return "observe"        # medium -> store as guessed / gather more
    return "ask" if importance >= cfg.ask_importance else "ignore"
