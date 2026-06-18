"""Self-tuning forgetting (#6). Run: pytest -q tests/test_tuning.py"""
import sys, os, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from fernme import tuning
from fernme.service import FernService


def test_tuner_adapts_to_drift():
    drifting = tuning.tune_decay(drift=True)
    stationary = tuning.tune_decay(drift=False)
    # under drift, forgetting helps -> picks a positive decay
    assert drifting["best_lam"] > 0
    # stationary -> forgetting only loses info -> picks a lower (often zero) rate
    assert stationary["best_lam"] <= drifting["best_lam"]


def test_autotune_sets_config():
    fd, p = tempfile.mkstemp(suffix=".db"); os.close(fd); os.remove(p)
    svc = FernService(p)
    before = svc.cfg.lam
    res = svc.autotune_decay(drift=True)
    assert svc.cfg.lam == res["best_lam"]
    assert isinstance(res["scores"], dict)
