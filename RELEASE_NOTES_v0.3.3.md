# FERNme v0.3.3 - Persistence fix

This release fixes bounded-card forgetting caused by style and mood noise crowding
out durable facts.

## Changed

- Style tags are no longer persisted as durable graph edges during normal writes.
  They remain available as transient recent-event guidance for `style_card()`.
- Compact cards exclude `style:*`, `mood:*`, and `mood_ema` / `mood_prev`
  numeric fields, including for older databases that already contain those edges.
- Text arousal and mood magnitude now contribute to per-attribute salience for
  facts mapped from the same turn.
- Identity namespaces such as `name`, `company`, `affiliation`, and `position`
  receive a salience floor so one-time facts resist passive decay.
- Compact-card ranking now includes salience, allowing important identity facts
  to surface in bounded cards even when lower-frequency than routine preferences.
- Superseded edges are excluded from compact cards, so salience never locks in an
  old identity fact after a stated replacement.
- Live identity facts are floor-exempt during passive decay when
  `identity_sticky=True`, so a once-stated employer/name-style fact persists
  until explicitly superseded. Superseded identity edges are not sticky.

## Compatibility

- No schema change and no migration required. Existing `salience`, `fast`, and
  mood fields continue to load and save normally.
- Set `salience_beta = 0` to restore the old decay behavior for salience. Card
  noise filtering remains default-on.
- Set `identity_sticky = False` to restore old decay-drop behavior for identity
  facts as well.
