"""Central hyperparameters for FERN. Every tunable lives here so experiments
are reproducible and the paper can report exact settings."""
import math
from dataclasses import dataclass, field


DEFAULT_LAM = 0.02
DEFAULT_VOLATILITY_HALF_LIVES = {
    "permanent": 3650.0,
    "slow": 200.0,
    "preference": 14.0,
    "habit": 90.0,
    "volatile": 7.0,
    "style": math.log(2.0) / DEFAULT_LAM,
    "association": 5.0,
}
DEFAULT_CONFIDENCE_HALF_LIVES = {
    "permanent": 3650.0,
    "slow": math.log(2.0) / DEFAULT_LAM,
    "preference": math.log(2.0) / DEFAULT_LAM,
    "habit": math.log(2.0) / DEFAULT_LAM,
    "volatile": 14.0,
    "style": math.log(2.0) / DEFAULT_LAM,
    "association": math.log(2.0) / DEFAULT_LAM,
}


def species_decay_from_half_lives(half_lives: dict, lam: float = DEFAULT_LAM) -> dict:
    """Convert target half-life days into lam-relative decay multipliers."""
    base_half_life = math.log(2.0) / max(float(lam), 1e-12)
    return {
        species: base_half_life / max(float(days), 1e-12)
        for species, days in half_lives.items()
    }


@dataclass(frozen=True)
class Config:
    # --- Hebbian write (write/hebbian.py) ---
    alpha: float = 1.5        # user->attr learn rate
    beta: float = 1.0         # attr<->attr (associative) learn rate
    assoc_min_users: int = 2  # cross-user assoc visibility threshold
    w_max: float = 9.0        # fuzzy scale ceiling (Zadeh, single-digit on the wire)
    gamma: float = 0.6        # confidence growth rate: conf = 1 - exp(-gamma * hits)

    # --- Decay / forgetting (ACT-R, batch) ---
    lam: float = DEFAULT_LAM  # SLOW weight decay per day (durable identity)
    alpha_fast: float = 2.0   # fast-lane learn rate (recent context)
    lam_fast: float = 0.40    # FAST weight decay per day (fades quickly)
    beta_fast: float = 0.5    # how much the fast lane boosts ranking
    floor: float = 1.0        # drop edges below this after decay
    bl_decay: float = 0.5     # ACT-R base-level decay exponent d
    # --- salience (emotional/behavioral significance -> slower forgetting) ---
    salience_beta: float = 0.5    # 0 = OFF (old decay behavior); >0: salient edges decay slower
    salience_neg: float = 0.5     # dislikes (negative edges) get this salience floor
    salience_decay: float = 0.25  # salience itself fades at lam*this (scars heal, slowly)
    salience_identity: float = 0.8        # salience floor for identity-like facts
    salience_w_intensity: float = 0.6     # arousal weight for emotional salience
    salience_w_moodmag: float = 0.4       # absolute mood weight
    salience_intensity_norm: float = 3.0  # intensity value that maps to about 1.0
    salience_card_boost: float = 0.5      # salience lift in compact-card ranking
    identity_sticky: bool = True          # permanent facts persist until superseded

    # --- resolution / temperature decay (resolution.py); ON after R5 drift+retention gate ---
    resolution: bool = True
    res_w_explicit: float = 0.35
    res_w_repeated: float = 0.15
    res_w_recent: float = 0.05
    res_w_corrob: float = 0.25      # reserved for v1 evidence scans
    res_w_outcome: float = 0.20     # reserved for v1 evidence scans
    res_repeat_hits: int = 3
    heat_gain: float = 1.0
    resolution_cap_non_override: float = 0.95
    temperature_floor_non_override: float = 0.05
    # Human-readable target half-lives in days for volatility classes.
    volatility_half_lives: dict = field(
        default_factory=lambda: dict(DEFAULT_VOLATILITY_HALF_LIVES))
    # Trust/confidence half-lives. Middle classes are conservative: no slower
    # than flat confidence decay unless tuned later with evidence.
    confidence_half_lives: dict = field(
        default_factory=lambda: dict(DEFAULT_CONFIDENCE_HALF_LIVES))
    # ON by default: use volatility-aware recency and contradiction verify.
    volatility_confidence: bool = True
    verify_age_enabled: bool = False           # age-only verify is future work
    verify_age_halflives: float = 1.5          # inferred facts verify sooner
    verify_age_halflives_stated: float = 3.0   # stated facts are trusted longer
    verify_conflict_threshold: float = 0.5      # high polarity conflict verifies immediately

    @property
    def species_decay(self) -> dict:
        """Derived-only decay multipliers. Edit volatility_half_lives, not this."""
        return species_decay_from_half_lives(self.volatility_half_lives, self.lam)
    phase_crystal: float = 0.95

    # --- curation / editing policy (curation.py); OFF by default (additive) ---
    curation: bool = False        # detect conflicts, supersede (tombstone) or ask
    curation_ask_threshold: float = 0.4  # min importance to escalate a tension

    # --- meaning per memory (glossary.py); free context + cheap/templated gloss ---
    capture_context: bool = True  # store the sentence a memory came from (no LLM)
    auto_gloss: bool = True        # fill missing glosses from namespace templates

    # --- typed entity layer (entity/card integration remains opt-in) ---
    entities: bool = False
    entity_aggregation: bool = False
    canonicalization_queue_cap: int = 50
    canonicalization_ttl_days: float = 90.0
    canonicalization_min_score: float = 0.55
    canonicalization_low_confidence: float = 0.40

    # --- Differential / population-prior encoding (prior/population.py) ---
    theta: float = 2.0        # store a user edge only if |w_user - w_prior| > theta

    # --- Retrieval (retrieve/) ---
    hops: int = 2             # spreading-activation hops
    top_n: int = 8            # max attributes on the wire card
    card_exclude_ns: frozenset = field(default_factory=frozenset)
    # Extra namespaces to keep out of the compact card, merged with built-ins.

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
