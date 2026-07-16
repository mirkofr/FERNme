"""Presentation-only hierarchical memory map."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from fernme.hierarchy import build_hierarchy


def test_hierarchy_collapses_tags_under_strongest_anchor():
    flat = {
        "nodes": [
            {"id": "person:mrs-reyes", "kind": "person", "label": "Mrs Reyes", "size": 2},
            {"id": "project:orbit-newmarket", "kind": "project", "label": "ORB", "size": 8},
            {"id": "connection:helped-connect-orbitlabs", "kind": "connection", "label": "helped", "size": 1},
            {"id": "source_note:memory-people-mrs-reyes-md", "kind": "source_note", "label": "note", "size": 1},
        ],
        "edges": [
            {"source": "person:mrs-reyes", "target": "connection:helped-connect-orbitlabs", "weight": 4, "assoc": True},
            {"source": "project:orbit-newmarket", "target": "connection:helped-connect-orbitlabs", "weight": 2, "assoc": True},
            {"source": "person:mrs-reyes", "target": "source_note:memory-people-mrs-reyes-md", "weight": 3, "assoc": True},
            {"source": "person:mrs-reyes", "target": "project:orbit-newmarket", "weight": 5, "assoc": True},
        ],
    }

    h = build_hierarchy(flat)

    anchors = {n["id"] for n in h["anchors"]}
    assert {"person:mrs-reyes", "project:orbit-newmarket"} <= anchors
    assert h["assignments"]["connection:helped-connect-orbitlabs"] == "person:mrs-reyes"
    assert h["assignments"]["source_note:memory-people-mrs-reyes-md"] == "person:mrs-reyes"
    assert any(
        e["source"] == "person:mrs-reyes" and e["target"] == "project:orbit-newmarket"
        for e in h["edges"]
    )


def test_hierarchy_projects_user_edges_to_collapsed_anchors():
    flat = {
        "nodes": [
            {"id": "user:alex", "kind": "user", "label": "Alex", "size": 9},
            {"id": "person:dana-reyes", "kind": "person", "label": "Dana", "size": 2},
            {"id": "project:atlas-journal", "kind": "project", "label": "Atlas", "size": 3},
            {"id": "topic:archive-planning", "kind": "topic", "label": "Archive", "size": 1},
        ],
        "edges": [
            {"source": "user:alex", "target": "person:dana-reyes", "weight": 4, "known": True},
            {"source": "user:alex", "target": "project:atlas-journal", "weight": 3, "known": True},
            {"source": "user:alex", "target": "topic:archive-planning", "weight": 2, "known": False},
            {"source": "person:dana-reyes", "target": "topic:archive-planning", "weight": 5, "assoc": True},
        ],
    }

    h = build_hierarchy(flat)

    owner_edges = {(e["source"], e["target"]): e for e in h["owner_edges"]}
    assert ("user:alex", "person:dana-reyes") in owner_edges
    assert ("user:alex", "project:atlas-journal") in owner_edges
    assert owner_edges[("user:alex", "person:dana-reyes")]["weight"] == 6
    assert owner_edges[("user:alex", "person:dana-reyes")]["owner_edge"] is True


def test_hierarchy_manual_promote_demote_is_presentation_only():
    flat = {
        "nodes": [
            {"id": "person:a", "kind": "person", "label": "A", "size": 2},
            {"id": "topic:x", "kind": "topic", "label": "X", "size": 1},
        ],
        "edges": [{"source": "person:a", "target": "topic:x", "weight": 1}],
    }
    h = build_hierarchy(flat, overrides={"promote": ["topic:x"], "demote": ["person:a"]})
    anchors = {n["id"] for n in h["anchors"]}
    assert "topic:x" in anchors
    assert "person:a" not in anchors


def test_surface_match_keeps_person_tags_under_person_anchor():
    flat = {
        "nodes": [
            {"id": "person:mrs-reyes", "kind": "person", "label": "Mrs Reyes", "size": 2},
            {"id": "project:orbit-newmarket", "kind": "project", "label": "ORB", "size": 9},
            {"id": "linked_label:mrs-reyes", "kind": "linked_label", "label": "Mrs Reyes", "size": 1},
        ],
        "edges": [
            {"source": "project:orbit-newmarket", "target": "linked_label:mrs-reyes", "weight": 20},
            {"source": "person:mrs-reyes", "target": "linked_label:mrs-reyes", "weight": 1},
        ],
    }

    h = build_hierarchy(flat)

    assert h["assignments"]["linked_label:mrs-reyes"] == "person:mrs-reyes"
    mrs = next(n for n in h["anchors"] if n["id"] == "person:mrs-reyes")
    assert mrs["child_count"] == 1
