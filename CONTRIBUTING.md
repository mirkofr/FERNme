# Contributing to FERNme

Thanks for your interest. FERNme is an Apache-2.0 research preview maintained by Acquilab Inc.

## Setup
```bash
pip install -e ".[dev,api]"
pytest -q          # 77 tests should pass
```

## Ground rules
- **Tested or it doesn't merge.** Every behavior change ships with a test.
- **Keep the hot path LLM-free.** The per-turn read/write path must stay deterministic;
  LLM use is gated/offline only.
- **Be honest in claims.** Mark simulated results as simulated; don't upgrade
  "we propose" to "we demonstrate" without data.
- Run the experiments if you touch the engine: `python -m fernme.eval.<name>`.

## Submitting
1. Fork, branch, add tests, `pytest -q`.
2. Open a PR describing the change and which tests cover it.
3. By contributing you agree your contribution is licensed under Apache-2.0.

## Security
See [SECURITY.md](SECURITY.md). Report vulnerabilities privately, not via public issues.
