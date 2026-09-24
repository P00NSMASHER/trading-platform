# Step 12 — Graph-Aware Surveillance Features

`src/graph_feature_engine.py` converts the Step-11 point-in-time intelligence graph and Step-4 market-surveillance feature vectors into additional relationship-aware features. It is research/surveillance-only and does not produce trade direction, expected-return, target-price, sizing, or order instructions.

## Point-in-time policy

For every scored minute, graph visibility is evaluated at that exact timestamp.

- `live_surveillance` requires an edge's underlying relationship/event to have been observed and its source/relationship to have become public by the scoring timestamp.
- `historical_forensics` may use later-public adjudication to explain an earlier underlying event, but never back-projects a genuinely later event before its `observed_at` timestamp.
- Later enforcement facts therefore cannot silently become live historical features.

Step 12 also tightened Step 11: `_visible_edge` now requires `observed_at <= as_of` in both modes. Case-similarity output excludes future/unobserved cases entirely.

## Feature families

For each seed security/minute, the engine expands visible related securities up to a configured hop limit and calculates:

- related-security breadth by hop;
- confidence-weighted graph breadth with hop decay;
- count/fraction of related securities with contemporaneous feature vectors;
- synchronized equity-volume, option-volume, spread, and multivariate anomalies;
- max/mean related-security multivariate anomaly intensity;
- confidence- and distance-weighted peer anomaly intensity;
- propagation strength, which requires both the seed and its related-security neighborhood to be anomalous;
- minimum/mean graph distance to anomalous related securities;
- prior visible adjudicated/public case count;
- structural similarity to only those cases visible under the same point-in-time rules.

Case similarity is graph-structural. It is not a probability of wrongdoing and does not use future returns.

## Inputs

- Step-4 `feature_vectors.csv` (or a compatible subset containing the required anomaly fields).
- Step-11 SQLite graph.

Required feature columns are:

`minute_ts_utc`, `symbol`, `feature_status`, `equity_volume_z`, `equity_spread_z`, `option_volume_z`, and `multivariate_l2`.

## Outputs

- `graph_feature_vectors.csv`
- `graph_feature_manifest.json`

Rows are retained even when no graph security node exists, using `graph_feature_status=no_security_node`. Ambiguous symbol-to-security mappings fail closed instead of guessing.

## Synthetic demo

```bash
python src/graph_feature_engine.py \
  --feature-vectors data/examples/graph_feature_input.csv \
  --graph-db data/processed/graph_demo/cross_event_graph.sqlite \
  --output-dir data/processed/graph_feature_demo \
  --mode live_surveillance \
  --max-hops 2
```

The synthetic fixture is only an implementation check and contains no evidence of real-world detector performance.
