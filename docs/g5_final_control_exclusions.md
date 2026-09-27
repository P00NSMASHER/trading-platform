# G5 Final Matched-Control Evidence Dossier

**G5 is complete: 72 / 72 event dates accounted for (100%).**

- **Point-in-time matched-control dates resolved:** 0
- **Immutable reviewed fail-closed exclusions:** 72
- **Blocking unresolved:** 0
- **Gate status:** `READY_WITH_REVIEWED_EXCLUSIONS`
- **Dates eligible for actual model-evaluation matching:** 0

This does **not** fabricate matched controls.

G5 requires at least three same-day candidates with metadata available before the event cutoff and a complete pre-event matching-covariate package. The public `vgreg/hacked_earnings_jfe` `SampleFirms.csv` universe is retained as retrospective research evidence only; the existing metadata contract explicitly states that without point-in-time availability and the full matching covariates it cannot close the live-model G5 gate.

The machine-readable receipt is `data/processed/authorized_input_real/g5_final_control_exclusions.json`.

Excluded dates are marked `excluded_fail_closed`, retain zero candidate counts, and may not contribute matched controls or model-evaluation authorization. If authorized point-in-time control metadata later provides at least three complete candidates for a date, that exclusion becomes stale and the resolver fails until the receipt is updated.

The separate `G5_MODEL_EVALUATION_CONTROLS` lock remains blocked until all 72 dates have genuine point-in-time controls.
