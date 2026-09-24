# Step 5 — Point-in-time matched controls

`src/matched_control_generator.py` builds same-date, same-local-minute control windows for historical surveillance events.

## Design rules

- Matching uses **pre-event point-in-time metadata only**.
- Step-4 anomaly features are used only to establish that a window exists and meets the configured history status; anomaly values are never used in the distance function.
- Candidate metadata must have `effective_ts_utc <= treated_event_ts`.
- Candidate symbols with a known positive historical event on the same local date are excluded.
- Optional exclusion windows can remove other contaminated/unlabeled intervals.
- Same-sector and scheduled-event-status matching are enforced when those values are available, unless explicitly disabled.
- Numerical distance is a robust standardized RMS distance. Liquidity/size-like variables are `log1p` transformed before standardization.
- A per-component standardized-distance caliper rejects poor candidates before ranking.

## Metadata schema

Required columns:

- `symbol`
- `effective_ts_utc`

Default numerical covariates:

- `market_cap`
- `price`
- `trailing_21d_vol`
- `normal_minute_volume`
- `normal_minute_turnover`
- `normal_relative_spread`
- `option_liquidity`
- `institutional_ownership`
- `analyst_coverage`
- `borrow_cost`
- `pre_event_return`

Optional exact-match fields:

- `sector`
- `index_bucket`
- `scheduled_event_flag`
- `source_name`

## Outputs

- `matched_controls.csv` — ranked control windows.
- `match_events.csv` — per-treated-event status and match quality.
- `match_balance.csv` — before/after standardized-mean-difference diagnostics.
- `match_manifest.json` — provenance, settings, hashes and anti-lookahead policy.

The matcher has no trading output and must not receive future prices, announcement reactions, unreleased earnings surprise, enforcement outcomes, or other post-event variables.
