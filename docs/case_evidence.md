# Step 8 — Private case database and evidence generator

`src/case_evidence.py` turns an offline surveillance score into an immutable, reproducible investigation record. It is deliberately **not** an execution, alerting, or legal-determination system.

## Design rules

- SQLite database is local only.
- Core evidence tables are append-only: database triggers reject `UPDATE` and `DELETE`.
- Review/disposition changes are recorded as new `review_history` rows, never by overwriting the case.
- Review rows are SHA-256 hash chained.
- The model bundle, features, score file, matched-controls file, and manifests are recorded by filename, size, and SHA-256.
- Raw licensed/proprietary source files are **not embedded** into evidence bundles by default.
- Evidence exports never copy training labels, enforcement outcomes, BUY/SELL decisions, expected returns, target prices, position sizes, or order instructions.
- A surveillance case is explicitly not a finding that insider trading or MNPI misuse occurred.

## Database tables

- `case_record` — immutable detection snapshot.
- `case_timeline` — score and top-feature chronology.
- `feature_snapshot` — exact model-input feature values at the scored minute.
- `control_snapshot` — matched controls and their risk scores when available.
- `source_artifact` — provenance hashes.
- `review_history` — append-only human-review chain.

## Example

```bash
python src/case_evidence.py ingest \
  --db data/processed/case_demo/cases.sqlite \
  --case-id CASE-H001 \
  --sample-id H001:TREATED \
  --scores-csv data/processed/model_demo/holdout_scores.csv \
  --feature-vectors data/examples/model_training_feature_vectors.csv \
  --model-bundle data/processed/model_demo/model_bundle.joblib \
  --matched-controls data/examples/model_training_matched_controls.csv \
  --training-manifest data/processed/model_demo/training_manifest.json

python src/case_evidence.py review \
  --db data/processed/case_demo/cases.sqlite \
  --case-id CASE-H001 \
  --reviewer owner \
  --action review_started \
  --disposition under_review \
  --note "Synthetic prototype review"

python src/case_evidence.py export \
  --db data/processed/case_demo/cases.sqlite \
  --case-id CASE-H001 \
  --output-dir data/processed/case_demo/evidence
```

The export includes `case_summary.json`, `timeline.csv`, `feature_snapshots.csv`, `control_snapshots.csv`, `source_artifacts.csv`, `review_history.csv`, `provenance.json`, `integrity_manifest.json`, `README.txt`, and a ZIP of the bundle.
