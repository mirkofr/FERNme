# Phase 9 Option B Re-park Note

Date: 2026-07-06

Decision: FAIL the Phase 9 ship rule and keep `option-b-learned-volatility` parked.

The rebased branch passed the full test suite, and the flag-off harness report was byte-identical to current `main` at `d852fd7`. The learned-volatility synthetic check still validates the underlying prior with cold-start delta `0.000 +/- 0.000`.

The Phase 8 harness A/B did not show any treatment lift on the required drift and staleness regimes. With `learned_volatility=True`, FERNme pure and FERNme entities were identical to control on recall, stale-recall rate, action quality, and token estimate for static, abrupt-drift, gradual-drift, and staleness rows. This fails the required "more than 1 sd" improvement rule.

Measured report: `reports/phase9_option_b_ab.json`
