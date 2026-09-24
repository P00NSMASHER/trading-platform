# Feature engine

`src/feature_engine.py` converts Step-3 point-in-time baseline metrics into backward-looking surveillance feature vectors.

## Inputs

- `baseline_metrics.csv` from `baseline_engine.py` (required)
- `equity_minutes.csv` from `market_data_adapter.py` (optional but required for price-behavior features)
- `option_minutes.csv` from `market_data_adapter.py` (optional but required for call/put and options/equity activity features)

## Point-in-time rule

Every feature uses only the current minute and observations at or before that minute. The engine does not accept or construct future returns, future earnings surprises, public-announcement outcomes, enforcement outcomes, unreleased text, trade directions, or expected-return targets.

## Feature families

- Current same-minute normalized anomalies: equity volume, turnover, spread, option volume, option dollar volume.
- Baseline ratios: current equity/option activity divided by point-in-time historical baseline means.
- Options/equity descriptors: call-put imbalance and option contracts per 100 equity shares traded.
- Backward price behavior: 1/5/15/30-minute trailing returns and trailing realized volatility.
- Sequence features: 5/15/30-minute anomaly peaks, persistence counts, slopes, and short-horizon acceleration.
- Liquidity response: count of recent spread-widening minutes.
- Multivariate indicators: positive-side L2 anomaly norm, number of >=2-sigma components, and short-horizon change.

Robust z-scores are preferred when available; ordinary z-scores are used only as fallback.

## Output

`feature_vectors.csv` contains one surveillance feature vector per symbol/minute. `feature_manifest.json` records source hashes, policy constraints, thresholds, and status counts.

This component does **not** assign a probability of misconduct and does **not** produce a long/short or trade recommendation.
