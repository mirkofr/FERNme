"""Decay clock, neighbourhood association loading, offline tokenizer, harness
namespace fix. Synthetic data only."""
import random

from fernme.eval import harness as H
from fernme.retrieve import card as card_mod
from fernme.retrieve.activation import spread
from fernme.service import FernService
from fernme.store.sqlite_store import SQLiteStore

SITE = "fix.example"


def test_decay_keeps_last_seen_times_and_is_repeatable():
    svc = FernService(db_path=":memory:")
    svc.consent(SITE, "u", True)
    for t in (1.0, 2.0, 3.0, 4.0):
        svc.observe(SITE, "u", "chat", {"tags": ["diet:vegetarian"]}, ts=t)
    for t in (5.0, 6.0, 7.0, 8.0):
        svc.observe(SITE, "u", "chat", {"tags": ["diet:vegan"]}, ts=t)
    svc.decay(SITE, "u", now=9.0)
    edges = svc.store.load_user(SITE, "u").edges
    assert edges["diet:vegetarian"].last_reinforced == 4.0     # previously reset to 9.0
    assert edges["diet:vegan"].last_reinforced == 8.0
    w = {a: e.weight for a, e in edges.items()}
    svc.decay(SITE, "u", now=9.0)
    again = svc.store.load_user(SITE, "u").edges
    assert all(abs(again[a].weight - w[a]) < 1e-12 for a in w)
    assert "_decay_clock" not in svc.card(SITE, "u", now=10.0)["wire"]


def test_neighbourhood_loading_matches_full_graph(tmp_path, monkeypatch):
    monkeypatch.setattr(SQLiteStore, "_NEIGHBORHOOD_MIN_EDGES", 0)
    monkeypatch.setattr(SQLiteStore, "_NEIGHBORHOOD_MAX_FRACTION", 10.0)   # never fall back
    rng = random.Random(7)
    vocab = [f"pref:x{i}" for i in range(80)]
    svc = FernService(db_path=str(tmp_path / "n.db"))
    for i in range(40):
        svc.consent(SITE, f"u{i}", True)
        for t in range(6):
            svc.observe(SITE, f"u{i}", "chat", {"tags": rng.sample(vocab, 3)}, ts=float(t))
    for i in range(10):
        user = f"u{i}"
        ctx = rng.sample(vocab, 2)
        ug = svc.store.load_user(SITE, user)
        full = svc.store.load_assoc(SITE, user=user, min_users=svc.cfg.assoc_min_users)
        part = svc._assoc_for_recall(SITE, user, ug, ctx)
        a, b = spread(ug, full, ctx, 9.0, svc.cfg), spread(ug, part, ctx, 9.0, svc.cfg)
        assert set(a) == set(b)
        assert all(abs(a[k] - b[k]) < 1e-9 for k in a)
        assert len(part.edges) <= len(full.edges)


def test_tokenizer_never_downloads_without_permission(monkeypatch):
    monkeypatch.delenv("FERNME_TOKENIZER_DOWNLOAD", raising=False)
    monkeypatch.setattr(card_mod, "_ENC", None)
    monkeypatch.setattr(card_mod, "_ENC_TRIED", False)
    monkeypatch.setattr(card_mod, "_tiktoken_cached", lambda: False)
    import builtins
    real_import = builtins.__import__

    def guarded(name, *args, **kwargs):
        assert name != "tiktoken", "tiktoken must not be loaded when not cached"
        return real_import(name, *args, **kwargs)
    monkeypatch.setattr(builtins, "__import__", guarded)
    assert card_mod.estimate_tokens("user:u | pref:tea:9*") == 5


def test_harness_answer_keys_avoid_reserved_card_namespaces():
    excluded = card_mod.card_exclude_namespaces()
    for scenario in H.build_scenarios(0):
        for probe in scenario.probes:
            for attr in probe.relevant_attrs + probe.stale_attrs:
                assert attr.split(":", 1)[0] not in excluded, (scenario.name, attr)


def _slot_card(extra_events):
    svc = FernService(db_path=":memory:")
    svc.consent(SITE, "u", True)
    for t in range(10):
        svc.observe(SITE, "u", "chat", {"tags": ["city:harbor-town", "pref:tea"]}, ts=float(t))
    for ts, payload in extra_events:
        svc.observe(SITE, "u", "chat", payload, ts=ts)
    return {l["attr"]: i for i, l in enumerate(svc.card(SITE, "u", now=20.0)["links"])}


def test_confirmed_new_value_replaces_old_single_value_slot():
    ranks = _slot_card([(10.0, {"tags": ["city:river-city"]}), (11.0, {"tags": ["city:river-city"]})])
    assert ranks["city:river-city"] < ranks["city:harbor-town"]


def test_stated_new_value_replaces_old_even_once():
    ranks = _slot_card([(10.0, {"tags": ["city:river-city"], "source": "stated"})])
    assert ranks["city:river-city"] < ranks["city:harbor-town"]


def test_single_passing_mention_does_not_replace_a_fact():
    svc_ranks = _slot_card([(10.0, {"tags": ["city:river-city"], "source": "inferred"})])
    assert svc_ranks["city:harbor-town"] < svc_ranks["city:river-city"]
