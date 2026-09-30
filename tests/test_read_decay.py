"""Card-time decay on the user's activity clock (synthetic streams only)."""
from dataclasses import replace

from fernme.config import DEFAULT
from fernme.eval.cost_race import synthetic_stream
from fernme.service import FernService

SITE = "decay.example"


def _card_after_race(cfg):
    svc = FernService(db_path=":memory:", cfg=cfg)
    svc.consent(SITE, "u", True)
    for m in synthetic_stream(300):
        svc.observe(SITE, "u", "chat", {"tags": m["tags"], "text": m["text"]},
                    ts=float(m["turn"]))
    return svc.card(SITE, "u", now=300.5)


def _attrs(card):
    return {link["attr"] for link in card["links"]}


def test_old_tastes_leave_the_card_without_a_decay_job():
    card = _card_after_race(DEFAULT)
    assert {"topic:python", "food:croissant"}.isdisjoint(_attrs(card))
    assert {"topic:rust", "food:rice-bowl", "pref:mint-tea"} <= _attrs(card)


def test_flag_off_restores_stored_weights():
    card = _card_after_race(replace(DEFAULT, card_read_decay=False))
    assert {"topic:python", "food:croissant"} <= _attrs(card)


def test_faded_memories_still_fill_an_otherwise_empty_card():
    svc = FernService(db_path=":memory:")
    svc.consent(SITE, "u", True)
    for i, tag in enumerate(["option:a", "option:b", "option:c"]):
        svc.observe(SITE, "u", "option", {"tags": [tag]}, ts=float(i))
    assert _attrs(svc.card(SITE, "u", now=60.0)) == {"option:a", "option:b", "option:c"}


def test_user_who_is_away_keeps_their_card():
    svc = FernService(db_path=":memory:")
    svc.consent(SITE, "u", True)
    for t in range(10):
        svc.observe(SITE, "u", "chat", {"tags": ["pref:tea", "topic:chess"]}, ts=float(t))
    soon = svc.card(SITE, "u", now=10.0)
    much_later = svc.card(SITE, "u", now=400.0)
    assert _attrs(soon) == _attrs(much_later) == {"pref:tea", "topic:chess"}
    assert [l["w"] for l in soon["links"]] == [l["w"] for l in much_later["links"]]


def test_overrides_never_fade():
    svc = FernService(db_path=":memory:")
    svc.consent(SITE, "u", True)
    svc.edit(SITE, "u", "pref:dairy", 0)
    svc.edit(SITE, "u", "diet:vegetarian", 9)
    for t in range(1, 200):
        svc.observe(SITE, "u", "chat", {"tags": ["topic:news"]}, ts=float(t))
    links = {l["attr"]: l["w"] for l in svc.card(SITE, "u", now=200.0)["links"]}
    assert links.get("diet:vegetarian") == 9


def test_untimed_memories_do_not_fade_against_wall_clock_writes():
    svc = FernService(db_path=":memory:")
    svc.consent(SITE, "u", True)
    svc.observe(SITE, "u", "chat", {"tags": ["diet:vegan", "pref:concise"]})        # ts=0
    svc.observe(SITE, "u", "document", {"tags": ["topic:tax_forms"]}, ts=1.7e9)
    links = {l["attr"]: l["w"] for l in svc.card(SITE, "u", now=1.7e9 + 60)["links"]}
    assert links["diet:vegan"] >= 1 and links["pref:concise"] >= 1
    # and a card requested without a time is never decayed
    legacy = FernService(db_path=":memory:", cfg=replace(DEFAULT, card_read_decay=False))
    legacy.store = svc.store
    assert svc.card(SITE, "u", now=0)["wire"] == legacy.card(SITE, "u", now=0)["wire"]
