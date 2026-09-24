# Step 18 — Point-in-time metadata population pipeline

This layer turns Step-17 metadata source contracts into cumulative, hashed, privately staged input batches and recalculates historical-research readiness after every import.

## What it does

1. Strictly validates every selected source and its authorization/reference metadata.
2. Hashes the original file before import.
3. Copies it into an owner-private content-addressed staging path.
4. Updates a cumulative active metadata contract without editing previous source receipts.
5. Re-runs the Step-17 point-in-time resolver.
6. Records numeric coverage progress and readiness-gate transitions.
7. Appends a hash-chained batch receipt to `metadata_population_ledger.jsonl`.
8. Produces an immutable metadata-only batch report. Raw licensed/reference files are not copied into report directories.

The pipeline does **not** download, purchase, scrape, or authenticate to any data provider. Source files must already be lawfully available to the operator.

## Supported population lanes

- authorized Daily TAQ Master/reference exports (`security_master`) for historical listing exchange and/or daily shares outstanding;
- authorized I/B/E/S or official newswire timestamp exports (`announcement_timestamp`);
- public SEC Companyfacts/XBRL-derived shares facts (`shares_outstanding`) with explicit point-in-time `available_at`;
- point-in-time same-day control universes (`control_universe`).

EDGAR filing acceptance remains a public-time **proxy** and cannot be promoted to exact first-public earnings-release time merely by importing it.

## Fail-closed rules

- `authorized_reference_data` requires both `authorized=true` and a nonblank internal license/entitlement reference.
- public inputs require a nonblank official/public source reference.
- credential-like fields are forbidden from metadata contracts.
- live stolen information, leaked credentials, accidental private disclosures, and unauthorized private data remain prohibited source classifications.
- a future-filed shares fact cannot resolve an earlier historical date.
- a batch with an already-active identical source hash is a no-op and does not mutate the ledger.
- ledger hash-chain failure blocks additional imports.

## Coverage delta

Every receipt records changes in:

- exact announcement timestamps;
- primary-exchange resolution;
- Nasdaq/ITCH requirements;
- shares-outstanding coverage;
- same-day point-in-time control-universe readiness;
- transition of each Step-17 readiness gate.

This makes metadata acquisition incremental: a batch can close one gate without pretending the others are complete.

## Example

```bash
python src/metadata_population.py \
  --events data/processed/historical_events.csv \
  --symbol-dates data/processed/coverage_plan_real/symbol_date_requirements.csv \
  --source-contract config/metadata_sources.private.json \
  --runtime-dir private_runtime/metadata_population \
  --outdir data/processed/metadata_population \
  --source-id taq-master-2011-q2 \
  --batch-id taq-master-2011-q2
```

Verify the append-only ledger:

```bash
python src/metadata_population.py \
  --events data/processed/historical_events.csv \
  --symbol-dates data/processed/coverage_plan_real/symbol_date_requirements.csv \
  --source-contract config/metadata_sources.private.json \
  --runtime-dir private_runtime/metadata_population \
  --outdir data/processed/metadata_population \
  --verify-ledger
```

## Research boundary

Outputs are metadata readiness and surveillance-research artifacts only. The population layer has no BUY/SELL, expected-return, target-price, sizing, order, or execution interface.
