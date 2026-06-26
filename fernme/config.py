"""Central hyperparameters for FERN. Every tunable lives here so experiments
are reproducible and the paper can report exact settings."""
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Config:
    # --- Hebbian write (write/hebbian.py) ---
    alpha: float = 1.5        # user->attr learn rate
    beta: float = 1.0         # attr<->attr (associative) learn rate
    w_max: float = 9.0        # fuzzy scale ceiling (Zadeh, single-digit on the wire)
    gamma: float = 0.6        # confidence growth rate: conf = 1 - exp(-gamma * hits)

    # --- Decay / forgetting (ACT-R, batch) ---
    lam: float = 0.02         # SLOW weight decay per day (durable identity)
    alpha_fast: float = 2.0   # fast-lane learn rate (recent context)
    lam_fast: float = 0.40    # FAST weight decay per day (fades quickly)
    beta_fast: float = 0.5    # how much the fast lane boosts ranking
    floor: float = 1.0        # drop edges below this after decay
    bl_decay: float = 0.5     # ACT-R base-level decay exponent d
    # --- salience (emotional/behavioral significance -> slower forgetting) ---
    salience_beta: float = 0.5    # 0 = OFF (old decay behavior); >0: salient edges decay slower
    salience_neg: float = 0.5     # dislikes (negative edges) get this salience floor
    salience_decay: float = 0.25  # salience itself fades at lam*this (scars heal, slowly)
    salience_identity: float = 0.8        # floor for identity-namespace facts
    salience_w_intensity: float = 0.6     # arousal weight for emotional salience
    salience_w_moodmag: float = 0.4       # absolute mood weight
    salience_intensity_norm: float = 3.0  # intensity value that maps to about 1.0
    salience_card_boost: float = 0.5      # salience lift in compact-card ranking
    identity_sticky: bool = True          # identity facts persist until superseded

    # --- resolution / temperature decay (resolution.py); OFF by default ---
    resolution: bool = False
    res_w_explicit: float = 0.35
    res_w_repeated: float = 0.15
    res_w_recent: float = 0.05
    res_w_corrob: float = 0.25      # reserved for v1 evidence scans
    res_w_outcome: float = 0.20     # reserved for v1 evidence scans
    res_repeat_hits: int = 3
    heat_gain: float = 1.0
    resolution_cap_non_override: float = 0.95
    temperature_floor_non_override: float = 0.05
    species_decay: dict = field(default_factory=dict)  # empty == all species 1.0
    phase_crystal: float = 0.95

    # --- curation / editing policy (curation.py); OFF by default (additive) ---
    curation: bool = False        # detect conflicts, supersede (tombstone) or ask
    curation_ask_threshold: float = 0.4  # min importance to escalate a tension

    # --- meaning per memory (glossary.py); free context + cheap/templated gloss ---
    capture_context: bool = True  # store the sentence a memory came from (no LLM)
    auto_gloss: bool = True        # fill missing glosses from namespace templates

    # --- Differential / population-prior encoding (prior/population.py) ---
    theta: float = 2.0        # store a user edge only if |w_user - w_prior| > theta

    # --- Retrieval (retrieve/) ---
    hops: int = 2             # spreading-activation hops
    top_n: int = 8            # max attributes on the wire card

    # --- Wire encoding ---
    conf_known: float = 0.6   # confidence at/above which a link is treated as 'known' (act silently)

    # --- multi-signal confidence (confidence.py); weights sum to 1, all TUNABLE ---
    w_evidence: float = 0.30      # how much independent evidence (hits)
    w_consistency: float = 0.25   # absence of conflicting signal (A->B flips)
    w_taxonomy: float = 0.20      # how cleanly the input mapped to a known attribute
    w_recency: float = 0.15       # confirmed recently?
    w_outcome: float = 0.10       # did acting on it lead to good outcomes?
    conf_high: float = 0.85       # >= -> act silently
    conf_low: float = 0.45        # <  -> ask (if important) or ignore
    ask_importance: float = 0.5   # importance threshold to bother asking
    ask_budget: int = 3           # max clarifying asks per user (rate limit)


DEFAULT = Config()
