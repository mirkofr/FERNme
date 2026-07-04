"""Entity-aware card post-processing.

This module deliberately sits after base spreading activation. With flags off,
FernService still calls the original card compiler directly.
"""
from __future__ import annotations

from typing import Dict, List, Optional

from ..config import Config, DEFAULT
from ..core.graph import AssocGraph, UserGraph
from ..prior.population import PopulationPrior
from ..relations import DEFAULT_RELATIONS
from .activation import spread
from .card import (
    _conflict_for,
    _namespace,
    card_exclude_namespaces,
    compile_card,
    estimate_tokens,
)
from .. import resolution as _resolution


def card_token_estimate(wire: str) -> int:
    """Stable len/4 estimate used for entity-card budget tests."""
    return max(1, (len(wire) + 3) // 4)


def aggregate_entity_activation(
    activation: Dict[str, float],
    alias_to_entity: Dict[str, str],
    aliases_by_entity: Dict[str, List[str]],
    edge_weights: Dict[str, float],
    alias_scores: Optional[Dict[str, tuple]] = None,
) -> Dict[str, Dict]:
    """Return deterministic entity scores and representative aliases.

    The post-pass sums activation for aliases of the same entity. The highest
    weight alias represents that entity in downstream ranking; ties are lexical.
    """
    out: Dict[str, Dict] = {}
    for entity_id, aliases in sorted(aliases_by_entity.items()):
        active_aliases = sorted(a for a in aliases if a in edge_weights)
        if not active_aliases:
            continue
        if alias_scores:
            representative = sorted(
                active_aliases,
                key=lambda alias: (
                    -int(alias_scores.get(alias, (0, 0.0))[0]),
                    -float(alias_scores.get(alias, (0, 0.0))[1]),
                    alias,
                ),
            )[0]
            score_floor = max(alias_scores.get(alias, (0, 0.0)) for alias in active_aliases)
        else:
            representative = sorted(
                active_aliases,
                key=lambda alias: (-float(edge_weights.get(alias, 0.0)), alias),
            )[0]
            score_floor = (0, 0.0)
        out[entity_id] = {
            "activation": sum(float(activation.get(alias, 0.0)) for alias in active_aliases),
            "representative": representative,
            "aliases": active_aliases,
            "score_floor": score_floor,
        }
    return out


def compile_entity_card(
    ug: UserGraph,
    assoc: AssocGraph,
    seeds: List[str],
    now: float,
    prior: Optional[PopulationPrior],
    cfg: Config,
    entity_ctx: Dict,
) -> Dict:
    """Compile a card with optional alias aggregation and entity rendering."""
    base_card = compile_card(ug, assoc, seeds, now, prior, cfg)
    if not (cfg.entities or cfg.entity_aggregation):
        return base_card

    activation = spread(ug, assoc, seeds, now, cfg)
    edge_weights = {attr: edge.weight for attr, edge in ug.edges.items()}
    alias_to_entity = entity_ctx["alias_to_entity"]
    aliases_by_entity = entity_ctx["aliases_by_entity"]
    exclude_ns = card_exclude_namespaces(cfg)
    alias_scores = _individual_alias_scores(ug, activation, prior, cfg, exclude_ns)
    entity_scores = (
        aggregate_entity_activation(
            activation, alias_to_entity, aliases_by_entity, edge_weights, alias_scores
        )
        if cfg.entity_aggregation
        else {}
    )
    representative_for = {
        data["representative"]: entity_id for entity_id, data in entity_scores.items()
    }

    scored = []
    for attr, edge in ug.edges.items():
        if edge.source == "superseded" or _namespace(attr) in exclude_ns:
            continue
        entity_id = alias_to_entity.get(attr)
        if cfg.entity_aggregation and entity_id in entity_scores:
            if entity_scores[entity_id]["representative"] != attr:
                continue
            active = entity_scores[entity_id]["activation"]
        else:
            active = activation.get(attr, 0.0)
        idf = prior.idf(attr) if prior else 1.0
        real = 0 if edge.source == "guessed" else 1
        fast_boost = cfg.beta_fast * (edge.fast / cfg.w_max)
        salience_boost = cfg.salience_card_boost * edge.salience
        score = active * (idf + 1.0) + fast_boost + salience_boost
        scored.append((attr, max((real, score), entity_scores.get(entity_id, {}).get(
            "score_floor", (real, score))), edge))
    scored.sort(key=lambda row: (-row[1][0], -row[1][1], row[0]))
    top = scored[:cfg.top_n]

    base_parts = _base_parts(top, ug, now, cfg)
    parts = []
    links = []
    for attr, _score, edge in top:
        entity_id = alias_to_entity.get(attr)
        part = None
        if cfg.entities and entity_id:
            part = _render_entity_part(entity_id, attr, edge, activation, entity_ctx, cfg)
        if part is None:
            part = _base_part(attr, edge, ug, now, cfg)
        parts.append(part)
        link = {"attr": attr, "w": edge.wire_weight(cfg.w_max),
                "known": edge.confidence >= cfg.conf_known}
        if attr in representative_for or (cfg.entities and entity_id):
            entity = entity_ctx["entities"].get(entity_id, {})
            link["entity"] = entity.get("display_name")
            link["entity_kind"] = entity.get("kind")
        links.append(link)

    parts, links = _fit_budget(parts, links, base_parts, base_card["wire"], ug)
    wire = _wire(ug, parts)
    return {
        "wire": wire,
        "tokens": estimate_tokens(wire),
        "card_token_estimate": card_token_estimate(wire),
        "links": links,
        "numeric": _clean_numeric(ug),
    }


def _individual_alias_scores(
    ug: UserGraph,
    activation: Dict[str, float],
    prior: Optional[PopulationPrior],
    cfg: Config,
    exclude_ns: set,
) -> Dict[str, tuple]:
    scores = {}
    for attr, edge in ug.edges.items():
        if edge.source == "superseded" or _namespace(attr) in exclude_ns:
            continue
        idf = prior.idf(attr) if prior else 1.0
        real = 0 if edge.source == "guessed" else 1
        fast_boost = cfg.beta_fast * (edge.fast / cfg.w_max)
        salience_boost = cfg.salience_card_boost * edge.salience
        scores[attr] = (
            real,
            float(activation.get(attr, 0.0)) * (idf + 1.0) + fast_boost + salience_boost,
        )
    return scores


def _clean_numeric(ug: UserGraph) -> Dict:
    return {k: v for k, v in ug.numeric.items() if not k.startswith("mood")}


def _wire(ug: UserGraph, parts: List[str]) -> str:
    def _fmt(v):
        if isinstance(v, float) and v.is_integer():
            return str(int(v))
        return str(v)

    num = " ".join(f"{k}:{_fmt(v)}" for k, v in _clean_numeric(ug).items())
    return f"user:{ug.user} | " + " ".join(parts) + (f" | {num}" if num else "")


def _base_parts(top, ug: UserGraph, now: float, cfg: Config) -> List[str]:
    return [_base_part(attr, edge, ug, now, cfg) for attr, _score, edge in top]


def _base_part(attr: str, edge, ug: UserGraph, now: float, cfg: Config) -> str:
    mark = "*" if edge.confidence >= cfg.conf_known else "?"
    verify = (
        _resolution.needs_verify(attr, edge, now, cfg,
                                 conflict=_conflict_for(ug, attr, cfg))["verify"]
        if getattr(cfg, "volatility_confidence", False)
        else False
    )
    return f"{attr}:{edge.wire_weight(cfg.w_max)}{mark}" + ("~verify" if verify else "")


def _render_entity_part(entity_id: str, attr: str, edge, activation: Dict[str, float],
                        entity_ctx: Dict, cfg: Config) -> Optional[str]:
    entity = entity_ctx["entities"].get(entity_id)
    if entity is None:
        return None
    fields = entity_ctx["fields_by_entity"].get(entity_id, [])[:2]
    relations = _active_relations(entity_id, activation, entity_ctx, cfg)[:2]
    bits = [f"entity:{entity['display_name']}"]
    bits.extend(f"{row['field']}:{row['value']}" for row in fields)
    bits.extend(relations)
    mark = "*" if edge.confidence >= cfg.conf_known else "?"
    bits.append(f"via:{attr}:{edge.wire_weight(cfg.w_max)}{mark}")
    return " ".join(bits)


def _active_relations(entity_id: str, activation: Dict[str, float],
                      entity_ctx: Dict, cfg: Config) -> List[str]:
    rows = []
    for row in entity_ctx["relations_by_entity"].get(entity_id, []):
        if row["provenance"] != "stated":
            continue
        outbound = row["subject_id"] == entity_id
        other_id = row["object_id"] if outbound else row["subject_id"]
        if not _entity_alias_active(other_id, activation, entity_ctx):
            continue
        relation = row["relation"] if outbound else DEFAULT_RELATIONS.relations[row["relation"]].inverse
        other = entity_ctx["entities"].get(other_id, {})
        rendered = f"{relation}->{other.get('display_name', other_id)}"
        note = str(row.get("note", "")).strip()
        if note:
            rendered += f"({note})"
        rows.append((float(row["weight"]), row["relation"], other.get("display_name", other_id), rendered))
    rows.sort(key=lambda item: (-item[0], item[1], item[2]))
    return [item[3] for item in rows]


def _entity_alias_active(entity_id: str, activation: Dict[str, float], entity_ctx: Dict) -> bool:
    for alias in entity_ctx["aliases_by_entity"].get(entity_id, []):
        if float(activation.get(alias, 0.0)) > 0.0:
            return True
    return False


def _fit_budget(parts: List[str], links: List[Dict], base_parts: List[str],
                base_wire: str, ug: UserGraph):
    cap = card_token_estimate(base_wire)
    fitted_parts = list(parts)
    fitted_links = list(links)
    while fitted_parts and card_token_estimate(_wire(ug, fitted_parts)) > cap:
        idx = len(fitted_parts) - 1
        if (idx < len(base_parts) and fitted_parts[idx] != base_parts[idx]
                and len(fitted_parts[idx]) > len(base_parts[idx])):
            fitted_parts[idx] = base_parts[idx]
        else:
            fitted_parts.pop()
            fitted_links.pop()
    if not fitted_parts and base_parts:
        fitted_parts = [base_parts[0]]
        fitted_links = links[:1]
    if card_token_estimate(_wire(ug, fitted_parts)) > cap:
        fitted_parts = base_parts[:len(fitted_parts)]
    return fitted_parts, fitted_links
