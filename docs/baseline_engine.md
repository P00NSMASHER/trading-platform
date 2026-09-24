# Baseline engine

`src/baseline_engine.py` creates point-in-time historical baselines for surveillance features.

## Core rule

For an observation at local market minute `HH:MM` on date `D`, the baseline may use only the same symbol and same local minute from dates strictly earlier than `D`. The current observation is appended only after it has been scored. This prevents look-ahead contamination.

The default window is the most recent **21 prior local trading dates** for which the metric is present. The default minimum history is 10 observations.

## Metrics

Equity:
- trade count
- share volume
- dollar volume
- quoted spread
- relative quoted spread
- minute turnover, when point-in-time shares outstanding is available

Options:
- trade count
- contract volume
- dollar volume
- call volume
- put volume
- unique contracts traded
- quoted spread

## Scores

For each metric the engine writes:
- current value
- history count
- rolling mean / sample standard deviation
- rolling median / MAD
- conventional z-score
- robust MAD z-score
- current-value / historical-mean ratio
- history status: `insufficient`, `partial`, or `full`

`robust_zscore = 0.6744897502 * (x - median) / MAD` when MAD is positive.

## Turnover

Turnover is only calculated when a separate point-in-time shares file is supplied:

```csv
symbol,effective_date,shares_outstanding
TEST,2026-01-01,100000000
```

For each market observation the engine selects the latest shares record whose `effective_date` is **on or before** the observation's local date. Future share-count records are never used.

## Output

- `baseline_metrics.csv`
- `baseline_manifest.json`

This is a research/surveillance transform. It does not output trade direction, expected return, target price, order, or position size.
