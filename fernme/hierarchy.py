"""Presentation-only hierarchy for memory-map visualizations.

This module never mutates a database. It takes the existing flat graph payload
and returns anchor clusters that a UI can collapse or expand.
"""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Dict, Iterable, Mapping, MutableMapping, Optional


ANCHOR_NAMESPACES = {"person", "project", "company", "org", "relationship"}
UNCLUSTERED_ID = "__unclustered__"


def load_overrides(path: str | Path | None) -> Dict:
    """Load local presentation overrides from JSON.

    Supported keys:
      promote: ["tag:id", ...]
      demote: ["tag:id", ...]

    Invalid or missing files are treated as no overrides.
    """
    if not path:
        return {}
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _namespace(node_id: str, kind: str | None = None) -> str:
    if kind:
        return kind
    return node_id.split(":", 1)[0] if ":" in node_id else "attr"


def _weight(edge: Mapping) -> float:
    try:
        return float(edge.get("weight", 1.0) or 1.0)
    except (TypeError, ValueError):
        return 1.0


def _node_weight(node: Mapping) -> float:
    try:
        return float(node.get("size", 1.0) or 1.0)
    except (TypeError, ValueError):
        return 1.0


def _is_user_node(node: Mapping) -> bool:
    return node.get("kind") in {"user", "owner", "surface"} or str(node.get("id", "")).startswith("user:")


def _is_anchor(node: Mapping, promote: set[str], demote: set[str]) -> bool:
    node_id = str(node.get("id", ""))
    if node_id in demote:
        return False
    if node_id in promote:
        return True
    if _is_user_node(node):
        return False
    return _namespace(node_id, node.get("kind")) in ANCHOR_NAMESPACES


def _value_key(node_id: str) -> str:
    value = node_id.split(":", 1)[1] if ":" in node_id else node_id
    return "".join(ch for ch in value.lower() if ch.isalnum())


def _surface_parent(node_id: str, anchor_ids: Iterable[str]) -> str | None:
    """Prefer obvious surface matches before graph-weight assignment.

    Examples:
      linked_label:mrs-reyes -> person:mrs-reyes
      source_note:memory-people-mrs-reyes-md -> person:mrs-reyes
      obs_tag:orbitlabs -> company:orbitlabs

    This is presentation-only; it does not alter stored memory edges.
    """
    node_key = _value_key(node_id)
    if not node_key:
        return None
    candidates = []
    for anchor_id in anchor_ids:
        anchor_key = _value_key(anchor_id)
        if anchor_key and anchor_key in node_key:
            candidates.append((len(anchor_key), anchor_id))
    if not candidates:
        return None
    return max(candidates)[1]


def build_hierarchy(flat_graph: Mapping, overrides: Optional[Mapping] = None) -> Dict:
    """Return collapsed/expandable hierarchy metadata for a flat graph payload.

    The input graph is not modified. Non-anchor tags are assigned to their
    strongest directly associated anchor. Anchor-to-anchor edges aggregate all
    underlying edges between their clusters.
    """
    overrides = overrides or {}
    promote = set(overrides.get("promote", []) or [])
    demote = set(overrides.get("demote", []) or [])

    raw_nodes = {str(n.get("id")): dict(n) for n in flat_graph.get("nodes", []) if n.get("id")}
    attr_nodes = {i: n for i, n in raw_nodes.items() if not _is_user_node(n)}
    anchor_ids = {i for i, n in attr_nodes.items() if _is_anchor(n, promote, demote)}

    adjacency: dict[str, list[tuple[str, float]]] = defaultdict(list)
    for edge in flat_graph.get("edges", []):
        source = str(edge.get("source", ""))
        target = str(edge.get("target", ""))
        if source not in attr_nodes or target not in attr_nodes:
            continue
        w = _weight(edge)
        adjacency[source].append((target, w))
        adjacency[target].append((source, w))

    assignments: dict[str, str] = {}
    clusters: dict[str, set[str]] = {a: {a} for a in anchor_ids}
    clusters[UNCLUSTERED_ID] = set()

    for node_id, node in attr_nodes.items():
        if node_id in anchor_ids:
            assignments[node_id] = node_id
            continue
        surface_parent = _surface_parent(node_id, anchor_ids)
        if surface_parent:
            parent = surface_parent
            assignments[node_id] = parent
            clusters.setdefault(parent, set()).add(node_id)
            continue
        candidates = [(nb, w) for nb, w in adjacency.get(node_id, []) if nb in anchor_ids]
        if candidates:
            parent, _ = max(candidates, key=lambda item: (item[1], _node_weight(attr_nodes[item[0]]), item[0]))
        else:
            parent = UNCLUSTERED_ID
        assignments[node_id] = parent
        clusters.setdefault(parent, set()).add(node_id)

    anchors = []
    for anchor_id, members in clusters.items():
        if anchor_id == UNCLUSTERED_ID and not members:
            continue
        if anchor_id == UNCLUSTERED_ID:
            node = {
                "id": anchor_id,
                "label": "unclustered",
                "kind": "cluster",
                "category": "facts",
                "cat": "facts",
                "color": "#8b93a1",
                "size": 1,
            }
        else:
            node = dict(attr_nodes[anchor_id])
        internal_strength = sum(_weight({"weight": w}) for m in members for _nb, w in adjacency.get(m, []))
        node["anchor"] = True
        node["child_count"] = max(0, len(members) - (0 if anchor_id == UNCLUSTERED_ID else 1))
        node["cluster_weight"] = round(internal_strength, 3)
        node["size"] = max(_node_weight(node), min(12.0, 2.0 + (internal_strength ** 0.5 if internal_strength else 0.0)))
        anchors.append(node)

    subnodes = []
    for node_id, parent in sorted(assignments.items()):
        if node_id == parent:
            continue
        n = dict(attr_nodes[node_id])
        n["parent"] = parent
        subnodes.append(n)

    agg_edges: dict[tuple[str, str], float] = defaultdict(float)
    expanded_edges = []
    for edge in flat_graph.get("edges", []):
        source = str(edge.get("source", ""))
        target = str(edge.get("target", ""))
        if source not in assignments or target not in assignments:
            continue
        ps, pt = assignments[source], assignments[target]
        w = _weight(edge)
        expanded_edges.append({
            "source": source,
            "target": target,
            "parentSource": ps,
            "parentTarget": pt,
            "weight": round(w, 3),
            "cross": ps != pt,
            "assoc": bool(edge.get("assoc", True)),
        })
        if ps == pt:
            continue
        key = tuple(sorted((ps, pt)))
        agg_edges[key] += w

    anchor_edges = [
        {"source": a, "target": b, "weight": round(w, 3), "aggregated": True}
        for (a, b), w in sorted(agg_edges.items(), key=lambda item: (-item[1], item[0]))
    ]

    return {
        "anchor_namespaces": sorted(ANCHOR_NAMESPACES),
        "anchors": sorted(anchors, key=lambda n: (-_node_weight(n), str(n.get("id")))),
        "subnodes": subnodes,
        "assignments": assignments,
        "edges": anchor_edges,
        "expanded_edges": expanded_edges,
        "stats": {
            "anchors": len(anchors),
            "subnodes": len(subnodes),
            "anchor_edges": len(anchor_edges),
            "unclustered": len(clusters.get(UNCLUSTERED_ID, set())),
        },
    }
