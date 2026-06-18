# Naming note

**FERNme** (Fuzzy-Edged Recall Network) is a *working codename*, carried over from
the paper skeleton's placeholder. It is **not** trademark-clear: "Fern" is a
common word and is already used by an unrelated dev-tools company (API/SDK
generation). No major *AI-memory* project uses it, so it's fine for a preprint /
repo, but pick a durable name before any product launch.

## Selection criteria
Distinctive, not a common English word, no collision in AI-memory or dev-tools,
.com / .ai and a GitHub org available, easy to say, not tied to one vertical.

## Candidate directions (verify availability before committing)
- **Descriptive-coined:** Memwick, Recalla, Memgraph (taken — avoid), Prefnet, Tendril.
- **Metaphor (graph/recall/growth):** Tendril, Mycelia, Rootline, Trellis.
- **Abstract/brandable:** Noema, Engram, Mneme, Cortexa, Remi.

Recommendation: shortlist 3, check USPTO + domain + GitHub org + npm/PyPI, then
decide. Keep `fernme` as the Python package import until the rename is final, then
do a single global replace (the system name is isolated to `__init__`, README,
and the paper).
