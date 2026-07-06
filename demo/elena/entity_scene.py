"""Fictional typed-entity scene for the Elena demo."""


SITE = "elena.journal"
USER = "elena"


def populate_elena_entities(svc, site: str = SITE, user: str = USER, ts: float = 1000.0):
    """Seed a small display-only entity layer through the public service API."""
    svc.observe(site, user, "entity_scene", {"tags": [
        "person:elena",
        "person:jonas",
        "person:jonas-k",
        "person:daniel",
        "project:memory-journal-platform",
    ]}, ts=ts)

    elena = svc.entity_create(site, user, "person", "Elena")
    jonas = svc.entity_create(site, user, "person", "Jonas")
    daniel = svc.entity_create(site, user, "person", "Daniel")
    platform = svc.entity_create(site, user, "project", "memory-journal-platform")

    for alias in ("person:elena", "name:elena-sofia-markovic"):
        svc.entity_link_alias(site, user, elena, alias)
    for alias in ("person:jonas", "person:jonas-k", "rel:jonas"):
        svc.entity_link_alias(site, user, jonas, alias)
    for alias in ("person:daniel", "rel:daniel"):
        svc.entity_link_alias(site, user, daniel, alias)
    svc.entity_link_alias(site, user, platform, "project:memory-journal-platform")

    svc.entity_set_field(site, user, jonas, "handle", "@jonas-k-demo", ts=ts + 0.1)
    svc.entity_relate(site, user, jonas, "friend_of", elena, ts=ts + 0.2)
    svc.entity_relate(site, user, daniel, "colleague_of", elena, ts=ts + 0.3)
    svc.entity_relate(site, user, elena, "works_on", platform, ts=ts + 0.4)
    svc.entity_relate(site, user, daniel, "works_on", platform, ts=ts + 0.5)
    svc.entity_add_fact(
        site, user, jonas, "friend_of", elena,
        "Jonas is part of Elena's fictional close-support circle.", ts=ts + 0.6)
    svc.entity_add_fact(
        site, user, daniel, "works_on", platform,
        "Daniel helps Elena shape the fictional memory-journal prototype.",
        ts=ts + 0.7)
    svc.entity_add_fact(
        site, user, daniel, "works_on", platform,
        "Daniel reviews the fictional platform notes before demo sessions.",
        ts=ts + 0.8)

    return {
        "elena": elena,
        "jonas": jonas,
        "daniel": daniel,
        "memory-journal-platform": platform,
    }
