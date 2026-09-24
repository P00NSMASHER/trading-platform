# External validation harness

Step 7 freezes the Step-6 model and tests it against separate historical case families without retraining, recalibration, or threshold tuning.

## Blindness design

Scoring and evaluation are deliberately separate commands.

`score` reads:

- the frozen Step-6 `model_bundle.joblib`;
- an external case registry with no label/outcome field;
- Step-4-compatible point-in-time feature vectors.

It **does not read ground truth**. It writes `external_scores.csv` and records the model-bundle SHA-256 before and after scoring.

`evaluate` is run only after scores exist. It joins a separate sealed ground-truth CSV and reports overall, case-family, and mechanism metrics using the exact frozen Step-6 threshold.

## Case families

Supported cohort labels:

- `edgar_hack` — stolen/nonpublic filing information;
- `fda_regulatory` — confidential regulatory or clinical decision information;
- `cross_security` — MNPI about one issuer associated with trading in another security;
- `ma_tip` — merger/acquisition tipper-tippee cases;
- `other_adjudicated` — other independently documented cases;
- `synthetic_demo` — plumbing-only fixtures.

The registry stores adjudication/source metadata for provenance, but those fields are never passed into the model feature matrix.

## Commands

Blind scoring:

```bash
python src/external_validation_harness.py score \
  --model-bundle data/processed/model_demo/model_bundle.joblib \
  --registry data/examples/external_validation_registry.csv \
  --feature-vectors data/examples/external_validation_feature_vectors.csv \
  --output-dir data/processed/external_validation_demo/scoring
```

Post-score evaluation:

```bash
python src/external_validation_harness.py evaluate \
  --scores-csv data/processed/external_validation_demo/scoring/external_scores.csv \
  --ground-truth data/examples/external_validation_ground_truth.csv \
  --output-dir data/processed/external_validation_demo/evaluation
```

## Non-goals

This harness does not retrieve MNPI, identify confidential content, generate trade direction, predict expected returns, route orders, or make a legal determination. It measures whether a frozen historical anomaly detector generalizes to independently documented case families.
