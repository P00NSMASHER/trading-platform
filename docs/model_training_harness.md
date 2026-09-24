# Step 6 — Offline model-training harness

`src/model_training_harness.py` trains a historical **market-surveillance** detector from Step-4 feature vectors and Step-5 matched controls.

It does **not** predict unreleased news direction and does not emit trade directions, expected returns, target prices, position sizes, or order instructions.

## Label construction

- Positive: the treated security/minute from each matched historical event.
- Negative: Step-5 matched-control security/minute windows.
- Each control inherits the treated issuer as its CV group, so a treated event and all matched controls stay together.

Hacked-but-not-adjudicated observations should remain excluded/unlabeled upstream rather than being forced into the negative class.

## Anti-leakage rules

The feature file is checked for field names that imply future prices, post-event data, unreleased earnings information, enforcement/prosecution outcomes, or trading outputs. The model uses only the explicit Step-4 feature allowlist.

The default temporal split is:

- Development: events before 2015.
- Final temporal holdout: events from 2015 onward.

Within the development period, `StratifiedGroupKFold` groups by treated issuer. Threshold selection and probability calibration use **only grouped out-of-fold development predictions**. The holdout is never used for tuning.

## Models

1. Elastic-net logistic regression with median imputation, missingness indicators, and standardization.
2. Shallow histogram gradient boosting with median imputation and missingness indicators.
3. Equal-weight blend calibrated with a logistic/Platt mapping trained on development OOF scores.

The alert threshold is selected on development OOF predictions subject to a configured false-positive-rate ceiling.

## Outputs

- `model_bundle.joblib` — offline fitted research models/calibrator/threshold.
- `holdout_scores.csv` — historical holdout surveillance scores for evaluation.
- `training_manifest.json` — provenance, split policy, metrics, and prohibited outputs.
- `elastic_net_coefficients.csv` — interpretable linear-model coefficients.
- `development_calibration.csv` — OOF calibration diagnostic bins.
- `cv_split_audit.json` — fold-level group-separation evidence.

A surveillance risk score is an anomaly-prioritization score, **not** a probability that insider trading or another crime occurred.
