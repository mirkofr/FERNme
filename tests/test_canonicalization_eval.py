import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from fernme.eval import canonicalization


def test_canonicalization_eval_is_deterministic_and_bounded():
    first = canonicalization.run(seeds=2)
    second = canonicalization.run(seeds=2)

    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)
    assert 0.0 <= first["summary"]["precision"]["mean"] <= 1.0
    assert 0.0 <= first["summary"]["recall"]["mean"] <= 1.0
